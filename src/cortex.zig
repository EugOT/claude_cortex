const std = @import("std");
const build_options = @import("build_options");

pub const version = build_options.version;

const max_store_bytes: usize = 64 * 1024 * 1024;
const max_rpc_line_bytes: usize = 1024 * 1024;
const duplicate_similarity_threshold: f64 = 0.86;

pub const ToolName = []const u8;

pub const tool_names = [_]ToolName{
    "add_rule",
    "anchor",
    "assess_coverage",
    "backfill_memories",
    "change_impact",
    "checkpoint",
    "codebase_analyze",
    "consolidate",
    "create_trigger",
    "curate_wiki",
    "detect_domain",
    "detect_gaps",
    "drill_down",
    "explore_features",
    "forget",
    "get_causal_chain",
    "get_methodology_graph",
    "get_project_story",
    "get_rules",
    "get_telemetry",
    "import_sessions",
    "ingest_codebase",
    "ingest_prd",
    "list_domains",
    "memory_stats",
    "narrative",
    "navigate_memory",
    "open_visualization",
    "query_methodology",
    "query_workflow_graph",
    "rate_memory",
    "rebuild_profiles",
    "recall",
    "recall_hierarchical",
    "record_session_end",
    "remember",
    "seed_project",
    "sync_instructions",
    "unified_search",
    "validate_memory",
    "wiki_adr",
    "wiki_link",
    "wiki_list",
    "wiki_purge",
    "wiki_read",
    "wiki_reindex",
    "wiki_rename",
    "wiki_verify",
    "wiki_write",
};

pub const RememberInput = struct {
    content: []const u8,
    tags: []const []const u8 = &.{},
    directory: []const u8 = "",
    domain: []const u8 = "",
    source: []const u8 = "user",
    force: bool = false,
    is_global: bool = false,
    supersedes: []const []const u8 = &.{},
};

pub const RecallInput = struct {
    query: []const u8,
    domain: []const u8 = "",
    directory: []const u8 = "",
    max_results: usize = 10,
    min_heat: f64 = 0.0,
    include_related: bool = false,
    include_superseded: bool = false,
};

const MemoryRecord = struct {
    kind: []const u8 = "memory",
    id: []const u8 = "",
    content: []const u8 = "",
    tags: []const []const u8 = &.{},
    directory: []const u8 = "",
    domain: []const u8 = "",
    source: []const u8 = "",
    created_at: []const u8 = "",
    heat: f64 = 0.0,
    is_global: bool = false,
    supersedes: []const []const u8 = &.{},
    redacted: bool = false,
    redaction_count: usize = 0,
    fingerprint: []const u8 = "",
};

const AccessRecord = struct {
    kind: []const u8 = "access",
    memory_id: []const u8 = "",
    accessed_at: []const u8 = "",
};

const ScoredMemory = struct {
    id: []const u8,
    content: []const u8,
    tags: []const []const u8,
    directory: []const u8,
    domain: []const u8,
    source: []const u8,
    created_at: []const u8,
    heat: f64,
    score: f64,
    access_count: u64,
    supersedes: []const []const u8,
    redacted: bool,
    redaction_count: usize,
    relation: []const u8,
};

const DuplicateMatch = struct {
    id: []const u8,
    similarity: f64,
};

const RedactionResult = struct {
    text: []u8,
    count: usize,
};

pub const Store = struct {
    allocator: std.mem.Allocator,
    io: std.Io,
    root: []const u8,
    memory_path: []const u8,
    wiki_root: []const u8,
    checkpoint_root: []const u8,

    pub fn init(
        allocator: std.mem.Allocator,
        io: std.Io,
        root: []const u8,
    ) !Store {
        const owned_root = try allocator.dupe(u8, root);
        errdefer allocator.free(owned_root);
        const memory_path = try std.fs.path.join(allocator, &.{ owned_root, "memories.jsonl" });
        errdefer allocator.free(memory_path);
        const wiki_root = try std.fs.path.join(allocator, &.{ owned_root, "wiki" });
        errdefer allocator.free(wiki_root);
        const checkpoint_root = try std.fs.path.join(allocator, &.{ owned_root, "checkpoints" });
        errdefer allocator.free(checkpoint_root);

        const cwd = std.Io.Dir.cwd();
        try cwd.createDirPath(io, owned_root);
        try cwd.createDirPath(io, wiki_root);
        try cwd.createDirPath(io, checkpoint_root);

        return .{
            .allocator = allocator,
            .io = io,
            .root = owned_root,
            .memory_path = memory_path,
            .wiki_root = wiki_root,
            .checkpoint_root = checkpoint_root,
        };
    }

    pub fn deinit(self: *Store) void {
        self.allocator.free(self.root);
        self.allocator.free(self.memory_path);
        self.allocator.free(self.wiki_root);
        self.allocator.free(self.checkpoint_root);
        self.* = undefined;
    }

    pub fn remember(self: *Store, input: RememberInput) ![]u8 {
        if (std.mem.trim(u8, input.content, " \t\r\n").len == 0) {
            return stringifyAlloc(self.allocator, .{
                .stored = false,
                .action = "rejected",
                .reason = "content is required",
            });
        }

        const resolved_domain = if (input.domain.len != 0)
            input.domain
        else
            detectDomain(input.directory);

        if (!input.force) {
            if (try self.findNearDuplicate(input.content, resolved_domain, input.directory)) |dupe| {
                defer self.allocator.free(dupe.id);
                return stringifyAlloc(self.allocator, .{
                    .stored = false,
                    .action = "rejected",
                    .reason = "near_duplicate",
                    .duplicate_id = dupe.id,
                    .similarity = dupe.similarity,
                    .threshold = duplicate_similarity_threshold,
                });
            }
        }

        const redacted = try redactSensitiveAlloc(self.allocator, input.content);
        defer self.allocator.free(redacted.text);
        const fingerprint = try fingerprintAlloc(self.allocator, redacted.text);
        defer self.allocator.free(fingerprint);

        const now = std.Io.Timestamp.now(self.io, .real).toMilliseconds();
        const hash = std.hash.Wyhash.hash(0, redacted.text);
        var nonce: u64 = undefined;
        self.io.random(std.mem.asBytes(&nonce));
        const id = try std.fmt.allocPrint(self.allocator, "{d}-{x}-{x}", .{ now, hash, nonce });
        defer self.allocator.free(id);
        const created_at = try std.fmt.allocPrint(self.allocator, "unix-ms:{d}", .{now});
        defer self.allocator.free(created_at);

        const rec: MemoryRecord = .{
            .kind = "memory",
            .id = id,
            .content = redacted.text,
            .tags = input.tags,
            .directory = input.directory,
            .domain = resolved_domain,
            .source = input.source,
            .created_at = created_at,
            .heat = if (input.force) 1.0 else 0.8,
            .is_global = input.is_global,
            .supersedes = input.supersedes,
            .redacted = redacted.count != 0,
            .redaction_count = redacted.count,
            .fingerprint = fingerprint,
        };

        const line = try stringifyAlloc(self.allocator, rec);
        defer self.allocator.free(line);
        try self.appendLine(self.memory_path, line);

        return stringifyAlloc(self.allocator, .{
            .stored = true,
            .memory_id = id,
            .action = "stored",
            .reason = "stored in native JSONL memory store",
            .heat = rec.heat,
            .redacted = rec.redacted,
            .redaction_count = rec.redaction_count,
            .supersedes = rec.supersedes,
        });
    }

    pub fn recall(self: *Store, input: RecallInput) ![]u8 {
        if (std.mem.trim(u8, input.query, " \t\r\n").len == 0) {
            return stringifyAlloc(self.allocator, .{
                .memories = &[_]ScoredMemory{},
                .intent = "general",
                .count = @as(usize, 0),
                .@"error" = "query is required",
            });
        }

        const data = try self.readFileOrEmpty(self.memory_path);
        defer self.allocator.free(data);

        var access_counts = try loadAccessCounts(self.allocator, data);
        defer freeStringMap(self.allocator, &access_counts);
        var superseded_ids = try loadSupersededIds(self.allocator, data);
        defer freeStringMapVoid(self.allocator, &superseded_ids);

        var scored: std.ArrayList(ScoredMemory) = .empty;
        defer scored.deinit(self.allocator);
        defer freeScoredMemories(self.allocator, scored.items);

        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            const rec = parsed.value;
            if (!std.mem.eql(u8, rec.kind, "memory")) continue;
            if (rec.id.len == 0 or rec.content.len == 0) continue;
            if (!input.include_superseded and superseded_ids.contains(rec.id)) continue;
            if (rec.heat < input.min_heat) continue;
            if (input.domain.len != 0 and !rec.is_global and !std.mem.eql(u8, rec.domain, input.domain)) continue;
            if (input.directory.len != 0 and !std.mem.eql(u8, rec.directory, input.directory)) continue;
            const access_count = access_counts.get(rec.id) orelse 0;
            const s = try scoreMemory(self.allocator, input.query, rec, access_count);
            if (s <= 0.0) continue;
            const item = try cloneScoredMemory(self.allocator, rec, s, access_count, "match");
            errdefer freeScoredMemory(self.allocator, item);
            try scored.append(self.allocator, item);
        }

        std.mem.sort(ScoredMemory, scored.items, {}, struct {
            fn lessThan(_: void, a: ScoredMemory, b: ScoredMemory) bool {
                return a.score > b.score;
            }
        }.lessThan);

        const keep = @min(scored.items.len, input.max_results);
        if (keep != 0) try self.logAccesses(scored.items[0..keep]);
        if (input.include_related) {
            var related = try self.findRelated(data, scored.items[0..keep], input.max_results);
            defer related.deinit(self.allocator);
            defer freeScoredMemories(self.allocator, related.items);
            return stringifyAlloc(self.allocator, .{
                .memories = scored.items[0..keep],
                .related = related.items,
                .intent = classifyIntent(input.query),
                .count = keep,
                .related_count = related.items.len,
                .include_superseded = input.include_superseded,
            });
        }
        return stringifyAlloc(self.allocator, .{
            .memories = scored.items[0..keep],
            .intent = classifyIntent(input.query),
            .count = keep,
            .include_superseded = input.include_superseded,
        });
    }

    pub fn memoryStats(self: *Store) ![]u8 {
        const data = try self.readFileOrEmpty(self.memory_path);
        defer self.allocator.free(data);
        var total: usize = 0;
        var access_events: usize = 0;
        var redacted_total: usize = 0;
        var supersession_edges: usize = 0;
        var heat_total: f64 = 0.0;
        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            if (std.mem.eql(u8, parsed.value.kind, "access")) {
                access_events += 1;
                continue;
            }
            if (!std.mem.eql(u8, parsed.value.kind, "memory")) continue;
            total += 1;
            heat_total += parsed.value.heat;
            redacted_total += parsed.value.redaction_count;
            supersession_edges += parsed.value.supersedes.len;
        }
        const avg = if (total == 0) 0.0 else heat_total / @as(f64, @floatFromInt(total));
        return stringifyAlloc(self.allocator, .{
            .total_memories = total,
            .episodic_count = total,
            .lexical_indexed_count = total,
            .active_count = total,
            .archived_count = @as(usize, 0),
            .stale_count = @as(usize, 0),
            .protected_count = @as(usize, 0),
            .avg_heat = avg,
            .total_entities = @as(usize, 0),
            .total_relationships = supersession_edges,
            .access_events = access_events,
            .redaction_count = redacted_total,
            .active_triggers = @as(usize, 0),
            .last_consolidation = "",
            .has_vector_search = false,
            .has_lexical_retrieval = true,
            .has_duplicate_gate = true,
            .has_secret_redaction = true,
        });
    }

    pub fn listDomains(self: *Store) ![]u8 {
        const data = try self.readFileOrEmpty(self.memory_path);
        defer self.allocator.free(data);
        var domains: std.ArrayList([]const u8) = .empty;
        defer domains.deinit(self.allocator);
        defer freeStringList(self.allocator, domains.items);

        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            const rec = parsed.value;
            if (!std.mem.eql(u8, rec.kind, "memory") or rec.domain.len == 0) continue;
            if (containsString(domains.items, rec.domain)) continue;
            const domain = try self.allocator.dupe(u8, rec.domain);
            errdefer self.allocator.free(domain);
            try domains.append(self.allocator, domain);
        }
        std.mem.sort([]const u8, domains.items, {}, struct {
            fn lessThan(_: void, a: []const u8, b: []const u8) bool {
                return std.mem.lessThan(u8, a, b);
            }
        }.lessThan);
        return stringifyAlloc(self.allocator, .{
            .domains = domains.items,
            .count = domains.items.len,
        });
    }

    pub fn memoryGraph(self: *Store) ![]u8 {
        const data = try self.readFileOrEmpty(self.memory_path);
        defer self.allocator.free(data);
        var nodes: std.ArrayList([]const u8) = .empty;
        var edges: std.ArrayList([]const u8) = .empty;
        defer nodes.deinit(self.allocator);
        defer edges.deinit(self.allocator);
        defer freeStringList(self.allocator, nodes.items);
        defer freeStringList(self.allocator, edges.items);

        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            const rec = parsed.value;
            if (!std.mem.eql(u8, rec.kind, "memory") or rec.id.len == 0) continue;
            const node = try self.allocator.dupe(u8, rec.id);
            errdefer self.allocator.free(node);
            try nodes.append(self.allocator, node);
            for (rec.supersedes) |old_id| {
                if (old_id.len == 0) continue;
                const edge = try std.fmt.allocPrint(self.allocator, "{s} supersedes {s}", .{ rec.id, old_id });
                errdefer self.allocator.free(edge);
                try edges.append(self.allocator, edge);
            }
        }

        return stringifyAlloc(self.allocator, .{
            .nodes = nodes.items,
            .edges = edges.items,
            .node_count = nodes.items.len,
            .edge_count = edges.items.len,
            .graph_kind = "supersession",
        });
    }

    pub fn wikiWrite(self: *Store, rel_path: []const u8, content: []const u8, mode: []const u8) ![]u8 {
        try validateWikiPath(rel_path);
        const full_path = try std.fs.path.join(self.allocator, &.{ self.wiki_root, rel_path });
        defer self.allocator.free(full_path);
        if (std.fs.path.dirname(full_path)) |parent| try std.Io.Dir.cwd().createDirPath(self.io, parent);

        const exists = fileExists(self.io, full_path);
        if (std.mem.eql(u8, mode, "create") and exists) {
            return stringifyAlloc(self.allocator, .{ .@"error" = "page already exists", .path = rel_path });
        }
        if (std.mem.eql(u8, mode, "append")) {
            const old = try self.readFileOrEmpty(full_path);
            defer self.allocator.free(old);
            const combined = if (old.len == 0)
                try self.allocator.dupe(u8, content)
            else
                try std.mem.concat(self.allocator, u8, &.{ old, "\n", content });
            defer self.allocator.free(combined);
            try std.Io.Dir.cwd().writeFile(self.io, .{ .sub_path = full_path, .data = combined });
        } else {
            try std.Io.Dir.cwd().writeFile(self.io, .{ .sub_path = full_path, .data = content });
        }

        return stringifyAlloc(self.allocator, .{
            .path = rel_path,
            .mode = mode,
            .created = !exists,
            .bytes_written = content.len,
            .root = self.wiki_root,
        });
    }

    pub fn wikiRead(self: *Store, rel_path: []const u8) ![]u8 {
        try validateWikiPath(rel_path);
        const full_path = try std.fs.path.join(self.allocator, &.{ self.wiki_root, rel_path });
        defer self.allocator.free(full_path);
        const content = try self.readFileOrEmpty(full_path);
        defer self.allocator.free(content);
        if (content.len == 0 and !fileExists(self.io, full_path)) {
            return stringifyAlloc(self.allocator, .{ .@"error" = "page not found", .path = rel_path });
        }
        return stringifyAlloc(self.allocator, .{
            .path = rel_path,
            .content = content,
            .content_length = content.len,
            .offset = @as(usize, 0),
            .root = self.wiki_root,
            .redirect_chain = &[_][]const u8{},
        });
    }

    pub fn wikiList(self: *Store) ![]u8 {
        var pages: std.ArrayList([]const u8) = .empty;
        defer pages.deinit(self.allocator);
        defer freeStringList(self.allocator, pages.items);
        var dir = self.openIterableDir(self.wiki_root) catch |err| switch (err) {
            error.FileNotFound => return stringifyAlloc(self.allocator, .{
                .root = self.wiki_root,
                .count = @as(usize, 0),
                .pages = &[_][]const u8{},
                .redirect_count = @as(usize, 0),
                .auto_generated_count = @as(usize, 0),
            }),
            else => return err,
        };
        defer dir.close(self.io);
        var walker = try dir.walk(self.allocator);
        defer walker.deinit();
        while (try walker.next(self.io)) |entry| {
            if (entry.kind == .file and std.mem.endsWith(u8, entry.path, ".md")) {
                const path = try self.allocator.dupe(u8, entry.path);
                errdefer self.allocator.free(path);
                try pages.append(self.allocator, path);
            }
        }
        std.mem.sort([]const u8, pages.items, {}, struct {
            fn lessThan(_: void, a: []const u8, b: []const u8) bool {
                return std.mem.lessThan(u8, a, b);
            }
        }.lessThan);
        return stringifyAlloc(self.allocator, .{
            .root = self.wiki_root,
            .count = pages.items.len,
            .pages = pages.items,
            .redirect_count = @as(usize, 0),
            .auto_generated_count = @as(usize, 0),
        });
    }

    pub fn checkpoint(self: *Store, action: []const u8, session_id: []const u8, payload: []const u8) ![]u8 {
        const safe_session = if (session_id.len == 0) "default" else session_id;
        try validateName(safe_session);
        const name = try std.fmt.allocPrint(self.allocator, "{s}.json", .{safe_session});
        defer self.allocator.free(name);
        const full_path = try std.fs.path.join(self.allocator, &.{ self.checkpoint_root, name });
        defer self.allocator.free(full_path);
        if (std.mem.eql(u8, action, "save")) {
            try std.Io.Dir.cwd().writeFile(self.io, .{ .sub_path = full_path, .data = payload });
            return stringifyAlloc(self.allocator, .{
                .action = "save",
                .saved = true,
                .session_id = safe_session,
                .path = full_path,
            });
        }
        if (std.mem.eql(u8, action, "restore")) {
            const content = try self.readFileOrEmpty(full_path);
            defer self.allocator.free(content);
            return stringifyAlloc(self.allocator, .{
                .action = "restore",
                .session_id = safe_session,
                .content = content,
                .found = content.len != 0,
            });
        }
        return stringifyAlloc(self.allocator, .{ .@"error" = "action must be save or restore" });
    }

    fn appendLine(self: *Store, path: []const u8, line: []const u8) !void {
        var file = try std.Io.Dir.cwd().createFile(self.io, path, .{
            .truncate = false,
            .lock = .exclusive,
        });
        defer file.close(self.io);
        const stat = try file.stat(self.io);
        try file.writePositionalAll(self.io, line, stat.size);
        try file.writePositionalAll(self.io, "\n", stat.size + line.len);
    }

    fn readFileOrEmpty(self: *Store, path: []const u8) ![]u8 {
        return std.Io.Dir.cwd().readFileAlloc(
            self.io,
            path,
            self.allocator,
            .limited(max_store_bytes),
        ) catch |err| switch (err) {
            error.FileNotFound => self.allocator.dupe(u8, ""),
            else => err,
        };
    }

    fn openIterableDir(self: *Store, path: []const u8) !std.Io.Dir {
        if (std.fs.path.isAbsolute(path)) {
            return std.Io.Dir.openDirAbsolute(self.io, path, .{ .iterate = true });
        }
        return std.Io.Dir.cwd().openDir(self.io, path, .{ .iterate = true });
    }

    fn findNearDuplicate(self: *Store, content: []const u8, domain: []const u8, directory: []const u8) !?DuplicateMatch {
        const data = try self.readFileOrEmpty(self.memory_path);
        defer self.allocator.free(data);
        var best: ?DuplicateMatch = null;
        errdefer if (best) |dupe| self.allocator.free(dupe.id);

        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            const rec = parsed.value;
            if (!std.mem.eql(u8, rec.kind, "memory")) continue;
            if (rec.content.len == 0 or rec.id.len == 0) continue;
            if (!rec.is_global and domain.len != 0 and !std.mem.eql(u8, rec.domain, domain)) continue;
            if (directory.len != 0 and rec.directory.len != 0 and !std.mem.eql(u8, rec.directory, directory)) continue;
            const similarity = try lexicalJaccard(self.allocator, content, rec.content);
            if (similarity < duplicate_similarity_threshold) continue;
            if (best == null or similarity > best.?.similarity) {
                if (best) |old| self.allocator.free(old.id);
                best = .{
                    .id = try self.allocator.dupe(u8, rec.id),
                    .similarity = similarity,
                };
            }
        }
        return best;
    }

    fn logAccesses(self: *Store, items: []const ScoredMemory) !void {
        const now = std.Io.Timestamp.now(self.io, .real).toMilliseconds();
        const accessed_at = try std.fmt.allocPrint(self.allocator, "unix-ms:{d}", .{now});
        defer self.allocator.free(accessed_at);
        for (items) |item| {
            const event: AccessRecord = .{
                .memory_id = item.id,
                .accessed_at = accessed_at,
            };
            const line = try stringifyAlloc(self.allocator, event);
            defer self.allocator.free(line);
            try self.appendLine(self.memory_path, line);
        }
    }

    fn findRelated(
        self: *Store,
        data: []const u8,
        selected: []const ScoredMemory,
        limit: usize,
    ) !std.ArrayList(ScoredMemory) {
        var related: std.ArrayList(ScoredMemory) = .empty;
        errdefer {
            freeScoredMemories(self.allocator, related.items);
            related.deinit(self.allocator);
        }
        if (selected.len == 0 or limit == 0) return related;

        var lines = std.mem.tokenizeScalar(u8, data, '\n');
        while (lines.next()) |line| {
            if (related.items.len >= limit) break;
            if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
            var parsed = std.json.parseFromSlice(MemoryRecord, self.allocator, line, .{
                .ignore_unknown_fields = true,
            }) catch continue;
            defer parsed.deinit();
            const rec = parsed.value;
            if (!std.mem.eql(u8, rec.kind, "memory")) continue;
            if (rec.id.len == 0 or selectedContains(selected, rec.id) or relatedContains(related.items, rec.id)) continue;
            if (!isRelatedToSelection(rec, selected)) continue;
            const item = try cloneScoredMemory(self.allocator, rec, 0.25, 0, "related");
            errdefer freeScoredMemory(self.allocator, item);
            try related.append(self.allocator, item);
        }
        return related;
    }
};

pub fn run(init_data: std.process.Init) !void {
    var args = std.process.Args.Iterator.init(init_data.minimal.args);
    _ = args.next();
    const command = args.next() orelse {
        try printUsage(init_data.io);
        return;
    };
    warnDeprecatedDatabaseUrl(init_data.io, init_data.environ_map);
    const root = try resolveRoot(init_data.gpa, init_data.environ_map);
    defer init_data.gpa.free(root);
    var store = try Store.init(init_data.gpa, init_data.io, root);
    defer store.deinit();

    if (std.mem.eql(u8, command, "mcp")) {
        try runMcp(init_data.gpa, init_data.io, &store);
    } else if (std.mem.eql(u8, command, "doctor")) {
        try writeJsonLine(init_data.gpa, init_data.io, try doctorJson(init_data.gpa, &store));
    } else if (std.mem.eql(u8, command, "remember")) {
        const result = try cliRemember(init_data.gpa, &store, &args);
        try writeJsonLine(init_data.gpa, init_data.io, result);
    } else if (std.mem.eql(u8, command, "recall")) {
        const result = try cliRecall(init_data.gpa, &store, &args);
        try writeJsonLine(init_data.gpa, init_data.io, result);
    } else if (std.mem.eql(u8, command, "stats")) {
        try writeJsonLine(init_data.gpa, init_data.io, try store.memoryStats());
    } else if (std.mem.eql(u8, command, "wiki")) {
        const result = try cliWiki(init_data.gpa, &store, &args);
        try writeJsonLine(init_data.gpa, init_data.io, result);
    } else if (std.mem.eql(u8, command, "checkpoint")) {
        const result = try cliCheckpoint(init_data.gpa, &store, &args);
        try writeJsonLine(init_data.gpa, init_data.io, result);
    } else if (std.mem.eql(u8, command, "hook")) {
        const name = args.next() orelse "unknown";
        try writeJsonLine(init_data.gpa, init_data.io, try hookJson(init_data.gpa, name));
    } else if (std.mem.eql(u8, command, "version")) {
        try writeJsonLine(init_data.gpa, init_data.io, try stringifyAlloc(init_data.gpa, .{ .version = version }));
    } else {
        try writeJsonLine(
            init_data.gpa,
            init_data.io,
            try stringifyAlloc(init_data.gpa, .{ .@"error" = "unknown command", .command = command }),
        );
    }
}

pub fn handleToolJson(allocator: std.mem.Allocator, store: *Store, name: []const u8, args: std.json.Value) ![]u8 {
    const obj: ?*const std.json.ObjectMap = if (args == .object) &args.object else null;
    if (std.mem.eql(u8, name, "remember")) {
        const tags = try getStringArray(allocator, objectGet(obj, "tags"));
        defer allocator.free(tags);
        const supersedes = try getStringArray(allocator, objectGet(obj, "supersedes"));
        defer allocator.free(supersedes);
        return store.remember(.{
            .content = getString(objectGet(obj, "content"), ""),
            .tags = tags,
            .directory = getString(objectGet(obj, "directory"), ""),
            .domain = getString(objectGet(obj, "domain"), ""),
            .source = getString(objectGet(obj, "source"), "user"),
            .force = getBool(objectGet(obj, "force"), false),
            .is_global = getBool(objectGet(obj, "is_global"), false),
            .supersedes = supersedes,
        });
    }
    if (std.mem.eql(u8, name, "recall") or std.mem.eql(u8, name, "unified_search")) {
        return store.recall(.{
            .query = getString(objectGet(obj, "query"), getString(objectGet(obj, "text"), "")),
            .domain = getString(objectGet(obj, "domain"), ""),
            .directory = getString(objectGet(obj, "directory"), ""),
            .max_results = getUsize(objectGet(obj, "max_results"), 10),
            .min_heat = getFloat(objectGet(obj, "min_heat"), 0.0),
            .include_related = getBool(objectGet(obj, "include_related"), false),
            .include_superseded = getBool(objectGet(obj, "include_superseded"), false),
        });
    }
    if (std.mem.eql(u8, name, "memory_stats") or std.mem.eql(u8, name, "get_telemetry")) {
        return store.memoryStats();
    }
    if (std.mem.eql(u8, name, "wiki_write")) {
        return store.wikiWrite(
            getString(objectGet(obj, "path"), ""),
            getString(objectGet(obj, "content"), ""),
            getString(objectGet(obj, "mode"), "create"),
        );
    }
    if (std.mem.eql(u8, name, "wiki_read")) return store.wikiRead(getString(objectGet(obj, "path"), ""));
    if (std.mem.eql(u8, name, "wiki_list")) return store.wikiList();
    if (std.mem.eql(u8, name, "wiki_reindex")) return store.wikiList();
    if (std.mem.eql(u8, name, "wiki_adr")) {
        const title = getString(objectGet(obj, "title"), "Untitled ADR");
        const body = try std.fmt.allocPrint(allocator,
            \\# {s}
            \\
            \\## Context
            \\{s}
            \\
            \\## Decision
            \\{s}
            \\
            \\## Consequences
            \\{s}
            \\
        , .{
            title,
            getString(objectGet(obj, "context"), ""),
            getString(objectGet(obj, "decision"), ""),
            getString(objectGet(obj, "consequences"), ""),
        });
        defer allocator.free(body);
        const slug = try slugAlloc(allocator, title);
        defer allocator.free(slug);
        const path = try std.fmt.allocPrint(allocator, "adr/{s}.md", .{slug});
        defer allocator.free(path);
        return store.wikiWrite(path, body, "create");
    }
    if (std.mem.eql(u8, name, "checkpoint")) {
        const payload = try stringifyAlloc(allocator, args);
        defer allocator.free(payload);
        return store.checkpoint(
            getString(objectGet(obj, "action"), "save"),
            getString(objectGet(obj, "session_id"), "default"),
            payload,
        );
    }
    if (std.mem.eql(u8, name, "detect_domain")) {
        return stringifyAlloc(allocator, .{
            .domain = detectDomain(getString(objectGet(obj, "cwd"), "")),
            .confidence = 0.75,
        });
    }
    if (std.mem.eql(u8, name, "list_domains")) {
        return store.listDomains();
    }
    if (std.mem.eql(u8, name, "get_methodology_graph") or
        std.mem.eql(u8, name, "query_workflow_graph") or
        std.mem.eql(u8, name, "navigate_memory"))
    {
        return store.memoryGraph();
    }
    if (std.mem.eql(u8, name, "query_methodology")) {
        return stringifyAlloc(allocator, .{
            .domain = detectDomain(getString(objectGet(obj, "cwd"), "")),
            .formatted = "Native Cortex is active. Recall memories with the recall tool before non-trivial work.",
            .memories = &[_][]const u8{},
        });
    }
    if (std.mem.eql(u8, name, "open_visualization")) {
        return stringifyAlloc(allocator, .{
            .opened = false,
            .reason = "browser visualizer was removed by the native rewrite",
            .replacement = "use recall, memory_stats, wiki_list, and query_workflow_graph JSON outputs",
        });
    }
    if (std.mem.eql(u8, name, "consolidate")) {
        return stringifyAlloc(allocator, .{
            .ok = false,
            .status = "not_implemented_native",
            .reason = "background consolidation was removed; native duplicate gating and supersession are enforced at write time",
        });
    }
    if (std.mem.eql(u8, name, "record_session_end")) {
        return stringifyAlloc(allocator, .{ .recorded = true, .native = true });
    }
    if (std.mem.eql(u8, name, "wiki_verify")) {
        return store.wikiList();
    }
    if (std.mem.eql(u8, name, "wiki_link") or std.mem.eql(u8, name, "wiki_purge") or
        std.mem.eql(u8, name, "wiki_rename"))
    {
        return stringifyAlloc(allocator, .{
            .ok = false,
            .tool = name,
            .status = "not_implemented_native",
            .message = "State-changing wiki compatibility operation is not implemented in the native core.",
        });
    }
    return stringifyAlloc(allocator, .{
        .ok = false,
        .tool = name,
        .status = "not_implemented_native",
        .message = "Advanced legacy implementation removed; native follow-up needed.",
    });
}

fn runMcp(allocator: std.mem.Allocator, io: std.Io, store: *Store) !void {
    var stdin_buf: [max_rpc_line_bytes]u8 = undefined;
    var stdout_file = std.Io.File.stdout();
    var stdin_file = std.Io.File.stdin();
    var reader = stdin_file.reader(io, &stdin_buf);
    while (try reader.interface.takeDelimiter('\n')) |line| {
        if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
        const response = handleRpc(allocator, store, line) catch |err|
            try rpcError(allocator, "null", -32603, @errorName(err));
        if (response) |json| {
            defer allocator.free(json);
            try stdout_file.writeStreamingAll(io, json);
            try stdout_file.writeStreamingAll(io, "\n");
        }
    }
}

fn handleRpc(allocator: std.mem.Allocator, store: *Store, line: []const u8) !?[]u8 {
    var parsed = try std.json.parseFromSlice(std.json.Value, allocator, line, .{});
    defer parsed.deinit();
    const root = parsed.value;
    if (root != .object) {
        const response = try rpcError(allocator, "null", -32600, "request must be a JSON object");
        return response;
    }
    const obj = root.object;
    const id_json = try valueJsonOrNull(allocator, obj.get("id"));
    defer allocator.free(id_json);
    const method = getString(obj.get("method"), "");

    if (std.mem.eql(u8, method, "initialize")) {
        var out: std.Io.Writer.Allocating = .init(allocator);
        errdefer out.deinit();
        try out.writer.print("{{\"jsonrpc\":\"2.0\",\"id\":{s},\"result\":", .{id_json});
        try out.writer.writeAll("{\"protocolVersion\":\"2025-11-25\",\"serverInfo\":{\"name\":\"cortex\",\"version\":");
        try std.json.Stringify.value(version, .{}, &out.writer);
        try out.writer.writeAll("},\"capabilities\":{\"tools\":{}}}}");
        const response = try out.toOwnedSlice();
        return response;
    }
    if (std.mem.eql(u8, method, "tools/list")) {
        const tools = try toolsListJson(allocator);
        defer allocator.free(tools);
        const response = try rpcResultRaw(allocator, id_json, tools);
        return response;
    }
    if (std.mem.eql(u8, method, "tools/call")) {
        const params = obj.get("params") orelse {
            const response = try rpcError(allocator, id_json, -32602, "params required");
            return response;
        };
        if (params != .object) {
            const response = try rpcError(allocator, id_json, -32602, "params must be object");
            return response;
        }
        const name = getString(params.object.get("name"), "");
        const arguments = params.object.get("arguments") orelse std.json.Value.null;
        const tool_json = try handleToolJson(allocator, store, name, arguments);
        defer allocator.free(tool_json);
        const wrapped = try mcpToolResult(allocator, tool_json);
        defer allocator.free(wrapped);
        const response = try rpcResultRaw(allocator, id_json, wrapped);
        return response;
    }
    if (std.mem.eql(u8, method, "notifications/initialized")) return null;
    const response = try rpcError(allocator, id_json, -32601, "method not found");
    return response;
}

fn mcpToolResult(allocator: std.mem.Allocator, json: []const u8) ![]u8 {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    try out.writer.writeAll("{\"content\":[{\"type\":\"text\",\"text\":");
    try std.json.Stringify.value(json, .{}, &out.writer);
    try out.writer.writeAll("}],\"isError\":false,\"structuredContent\":");
    try out.writer.writeAll(json);
    try out.writer.writeAll("}");
    return out.toOwnedSlice();
}

fn toolsListJson(allocator: std.mem.Allocator) ![]u8 {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    try out.writer.writeAll("{\"tools\":[");
    for (tool_names, 0..) |name, idx| {
        if (idx != 0) try out.writer.writeAll(",");
        try out.writer.writeAll("{\"name\":");
        try std.json.Stringify.value(name, .{}, &out.writer);
        try out.writer.writeAll(",\"description\":");
        try std.json.Stringify.value(toolDescription(name), .{}, &out.writer);
        try out.writer.writeAll(",\"inputSchema\":{\"type\":\"object\",\"additionalProperties\":true}}");
    }
    try out.writer.writeAll("]}");
    return out.toOwnedSlice();
}

fn rpcResultRaw(allocator: std.mem.Allocator, id_json: []const u8, result_json: []const u8) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "{{\"jsonrpc\":\"2.0\",\"id\":{s},\"result\":{s}}}",
        .{ id_json, result_json },
    );
}

fn rpcError(allocator: std.mem.Allocator, id_json: []const u8, code: i32, message: []const u8) ![]u8 {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    try out.writer.print(
        "{{\"jsonrpc\":\"2.0\",\"id\":{s},\"error\":{{\"code\":{d},\"message\":",
        .{ id_json, code },
    );
    try std.json.Stringify.value(message, .{}, &out.writer);
    try out.writer.writeAll("}}}");
    return out.toOwnedSlice();
}

fn doctorJson(allocator: std.mem.Allocator, store: *Store) ![]u8 {
    return stringifyAlloc(allocator, .{
        .ok = true,
        .version = version,
        .runtime = "native-zig",
        .root = store.root,
        .memory_path = store.memory_path,
        .wiki_root = store.wiki_root,
        .legacy_runtimes = "removed",
        .database_url = "not required by native file-backed store",
        .retrieval = "native lexical Jaccard scoring with heat and access reinforcement",
        .write_gate = "near-duplicate suppression unless force is explicit",
        .privacy = "obvious secret and DSN redaction before local persistence",
        .graph = "native supersession graph",
    });
}

fn cliRemember(allocator: std.mem.Allocator, store: *Store, args: *std.process.Args.Iterator) ![]u8 {
    var content: []const u8 = "";
    var domain: []const u8 = "";
    var directory: []const u8 = "";
    var force = false;
    var tags: std.ArrayList([]const u8) = .empty;
    var supersedes: std.ArrayList([]const u8) = .empty;
    defer tags.deinit(allocator);
    defer supersedes.deinit(allocator);
    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--content")) content = args.next() orelse "";
        if (std.mem.eql(u8, arg, "--domain")) domain = args.next() orelse "";
        if (std.mem.eql(u8, arg, "--directory")) directory = args.next() orelse "";
        if (std.mem.eql(u8, arg, "--tag")) try tags.append(allocator, args.next() orelse "");
        if (std.mem.eql(u8, arg, "--supersedes")) try supersedes.append(allocator, args.next() orelse "");
        if (std.mem.eql(u8, arg, "--force")) force = true;
    }
    return store.remember(.{
        .content = content,
        .domain = domain,
        .directory = directory,
        .tags = tags.items,
        .force = force,
        .supersedes = supersedes.items,
    });
}

fn cliRecall(allocator: std.mem.Allocator, store: *Store, args: *std.process.Args.Iterator) ![]u8 {
    _ = allocator;
    var query: []const u8 = "";
    var domain: []const u8 = "";
    var max_results: usize = 10;
    var include_related = false;
    var include_superseded = false;
    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--query")) query = args.next() orelse "";
        if (std.mem.eql(u8, arg, "--domain")) domain = args.next() orelse "";
        if (std.mem.eql(u8, arg, "--include-related")) include_related = true;
        if (std.mem.eql(u8, arg, "--include-superseded")) include_superseded = true;
        if (std.mem.eql(u8, arg, "--max-results")) {
            if (args.next()) |raw| max_results = std.fmt.parseInt(usize, raw, 10) catch 10;
        }
    }
    return store.recall(.{
        .query = query,
        .domain = domain,
        .max_results = max_results,
        .include_related = include_related,
        .include_superseded = include_superseded,
    });
}

fn cliWiki(allocator: std.mem.Allocator, store: *Store, args: *std.process.Args.Iterator) ![]u8 {
    _ = allocator;
    const action = args.next() orelse "list";
    if (std.mem.eql(u8, action, "write")) {
        return store.wikiWrite(args.next() orelse "", args.next() orelse "", "create");
    }
    if (std.mem.eql(u8, action, "read")) return store.wikiRead(args.next() orelse "");
    return store.wikiList();
}

fn cliCheckpoint(allocator: std.mem.Allocator, store: *Store, args: *std.process.Args.Iterator) ![]u8 {
    const action = args.next() orelse "restore";
    var session_id: []const u8 = "default";
    var content: []const u8 = "{}";
    var positional: usize = 0;
    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--session-id")) {
            session_id = args.next() orelse "default";
        } else if (std.mem.eql(u8, arg, "--content")) {
            content = args.next() orelse "{}";
        } else if (positional == 0) {
            session_id = arg;
            positional = 1;
        } else if (positional == 1) {
            content = arg;
            positional = 2;
        }
    }
    if (!std.mem.startsWith(u8, content, "{")) {
        const wrapped = try stringifyAlloc(allocator, .{ .content = content });
        defer allocator.free(wrapped);
        return store.checkpoint(action, session_id, wrapped);
    }
    return store.checkpoint(action, session_id, content);
}

fn hookJson(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    return stringifyAlloc(allocator, .{
        .ok = true,
        .hook = name,
        .runtime = "native-zig",
        .message = "native Cortex hook accepted event",
    });
}

fn resolveRoot(allocator: std.mem.Allocator, env: *std.process.Environ.Map) ![]u8 {
    if (env.get("CORTEX_HOME")) |value| if (value.len != 0) return allocator.dupe(u8, value);
    if (env.get("CLAUDE_PLUGIN_DATA")) |value| if (value.len != 0) return allocator.dupe(u8, value);
    if (env.get("HOME")) |home| return std.fs.path.join(allocator, &.{ home, ".claude", "methodology", "native" });
    return allocator.dupe(u8, ".cortex-native");
}

fn warnDeprecatedDatabaseUrl(io: std.Io, env: *std.process.Environ.Map) void {
    const value = env.get("CORTEX_DATABASE_URL") orelse return;
    if (std.mem.trim(u8, value, " \t\r\n").len == 0) return;
    var stderr_file = std.Io.File.stderr();
    stderr_file.writeStreamingAll(
        io,
        "warning: database_url is deprecated and ignored by native Cortex; " ++
            "use cortex_home or CORTEX_HOME for local storage.\n",
    ) catch return;
}

fn writeJsonLine(allocator: std.mem.Allocator, io: std.Io, json: []u8) !void {
    defer allocator.free(json);
    var stdout_file = std.Io.File.stdout();
    try stdout_file.writeStreamingAll(io, json);
    try stdout_file.writeStreamingAll(io, "\n");
}

fn printUsage(io: std.Io) !void {
    var stdout_file = std.Io.File.stdout();
    try stdout_file.writeStreamingAll(io,
        \\cortex native CLI
        \\commands: mcp, doctor, remember, recall, stats, wiki, checkpoint, hook, version
        \\
    );
}

fn stringifyAlloc(allocator: std.mem.Allocator, value: anytype) ![]u8 {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    try std.json.Stringify.value(value, .{}, &out.writer);
    return out.toOwnedSlice();
}

fn valueJsonOrNull(allocator: std.mem.Allocator, value: ?std.json.Value) ![]u8 {
    if (value) |v| return stringifyAlloc(allocator, v);
    return allocator.dupe(u8, "null");
}

fn objectGet(obj: ?*const std.json.ObjectMap, key: []const u8) ?std.json.Value {
    if (obj) |map| return map.get(key);
    return null;
}

fn getString(value: ?std.json.Value, default_value: []const u8) []const u8 {
    if (value) |v| switch (v) {
        .string => |s| return s,
        else => return default_value,
    };
    return default_value;
}

fn getBool(value: ?std.json.Value, default_value: bool) bool {
    if (value) |v| switch (v) {
        .bool => |b| return b,
        else => return default_value,
    };
    return default_value;
}

fn getUsize(value: ?std.json.Value, default_value: usize) usize {
    if (value) |v| switch (v) {
        .integer => |i| return if (i >= 0) @intCast(i) else default_value,
        else => return default_value,
    };
    return default_value;
}

fn getFloat(value: ?std.json.Value, default_value: f64) f64 {
    if (value) |v| switch (v) {
        .float => |f| return f,
        .integer => |i| return @floatFromInt(i),
        else => return default_value,
    };
    return default_value;
}

fn getStringArray(allocator: std.mem.Allocator, value: ?std.json.Value) ![]const []const u8 {
    var list: std.ArrayList([]const u8) = .empty;
    errdefer list.deinit(allocator);
    if (value) |v| if (v == .array) {
        for (v.array.items) |item| {
            if (item == .string) try list.append(allocator, item.string);
        }
    };
    return list.toOwnedSlice(allocator);
}

fn cloneTags(allocator: std.mem.Allocator, tags: []const []const u8) ![]const []const u8 {
    var list: std.ArrayList([]const u8) = .empty;
    errdefer {
        freeStringList(allocator, list.items);
        list.deinit(allocator);
    }
    for (tags) |tag| {
        const owned_tag = try allocator.dupe(u8, tag);
        errdefer allocator.free(owned_tag);
        try list.append(allocator, owned_tag);
    }
    return list.toOwnedSlice(allocator);
}

fn cloneScoredMemory(
    allocator: std.mem.Allocator,
    rec: MemoryRecord,
    score: f64,
    access_count: u64,
    relation: []const u8,
) !ScoredMemory {
    const id = try allocator.dupe(u8, rec.id);
    errdefer allocator.free(id);
    const content = try allocator.dupe(u8, rec.content);
    errdefer allocator.free(content);
    const tags = try cloneTags(allocator, rec.tags);
    errdefer {
        freeStringList(allocator, tags);
        allocator.free(tags);
    }
    const directory = try allocator.dupe(u8, rec.directory);
    errdefer allocator.free(directory);
    const domain = try allocator.dupe(u8, rec.domain);
    errdefer allocator.free(domain);
    const source = try allocator.dupe(u8, rec.source);
    errdefer allocator.free(source);
    const created_at = try allocator.dupe(u8, rec.created_at);
    errdefer allocator.free(created_at);
    const supersedes = try cloneTags(allocator, rec.supersedes);
    errdefer {
        freeStringList(allocator, supersedes);
        allocator.free(supersedes);
    }
    const owned_relation = try allocator.dupe(u8, relation);
    errdefer allocator.free(owned_relation);

    return .{
        .id = id,
        .content = content,
        .tags = tags,
        .directory = directory,
        .domain = domain,
        .source = source,
        .created_at = created_at,
        .heat = rec.heat,
        .score = score,
        .access_count = access_count,
        .supersedes = supersedes,
        .redacted = rec.redacted,
        .redaction_count = rec.redaction_count,
        .relation = owned_relation,
    };
}

fn freeScoredMemory(allocator: std.mem.Allocator, item: ScoredMemory) void {
    allocator.free(item.id);
    allocator.free(item.content);
    freeStringList(allocator, item.tags);
    allocator.free(item.tags);
    allocator.free(item.directory);
    allocator.free(item.domain);
    allocator.free(item.source);
    allocator.free(item.created_at);
    freeStringList(allocator, item.supersedes);
    allocator.free(item.supersedes);
    allocator.free(item.relation);
}

fn freeScoredMemories(allocator: std.mem.Allocator, items: []ScoredMemory) void {
    for (items) |item| freeScoredMemory(allocator, item);
}

fn freeStringList(allocator: std.mem.Allocator, items: []const []const u8) void {
    for (items) |item| allocator.free(item);
}

fn freeStringArrayList(allocator: std.mem.Allocator, list: *std.ArrayList([]const u8)) void {
    freeStringList(allocator, list.items);
    list.deinit(allocator);
}

fn freeStringMap(allocator: std.mem.Allocator, map: *std.StringHashMap(u64)) void {
    var keys = map.keyIterator();
    while (keys.next()) |key| allocator.free(key.*);
    map.deinit();
}

fn freeStringMapVoid(allocator: std.mem.Allocator, map: *std.StringHashMap(void)) void {
    var keys = map.keyIterator();
    while (keys.next()) |key| allocator.free(key.*);
    map.deinit();
}

fn loadAccessCounts(allocator: std.mem.Allocator, data: []const u8) !std.StringHashMap(u64) {
    var counts = std.StringHashMap(u64).init(allocator);
    errdefer freeStringMap(allocator, &counts);
    var lines = std.mem.tokenizeScalar(u8, data, '\n');
    while (lines.next()) |line| {
        var parsed = std.json.parseFromSlice(AccessRecord, allocator, line, .{
            .ignore_unknown_fields = true,
        }) catch continue;
        defer parsed.deinit();
        const event = parsed.value;
        if (!std.mem.eql(u8, event.kind, "access") or event.memory_id.len == 0) continue;
        if (counts.getPtr(event.memory_id)) |value| {
            value.* += 1;
        } else {
            const key = try allocator.dupe(u8, event.memory_id);
            errdefer allocator.free(key);
            try counts.put(key, 1);
        }
    }
    return counts;
}

fn loadSupersededIds(allocator: std.mem.Allocator, data: []const u8) !std.StringHashMap(void) {
    var ids = std.StringHashMap(void).init(allocator);
    errdefer freeStringMapVoid(allocator, &ids);
    var lines = std.mem.tokenizeScalar(u8, data, '\n');
    while (lines.next()) |line| {
        var parsed = std.json.parseFromSlice(MemoryRecord, allocator, line, .{
            .ignore_unknown_fields = true,
        }) catch continue;
        defer parsed.deinit();
        const rec = parsed.value;
        if (!std.mem.eql(u8, rec.kind, "memory")) continue;
        for (rec.supersedes) |id| {
            if (id.len == 0 or ids.contains(id)) continue;
            const key = try allocator.dupe(u8, id);
            errdefer allocator.free(key);
            try ids.put(key, {});
        }
    }
    return ids;
}

fn scoreMemory(allocator: std.mem.Allocator, query: []const u8, rec: MemoryRecord, access_count: u64) !f64 {
    var score: f64 = 0.0;
    const similarity = try lexicalJaccard(allocator, query, rec.content);
    if (similarity > 0.0) score += similarity * 8.0;
    if (std.ascii.indexOfIgnoreCase(rec.content, query) != null) score += 4.0;

    var query_tokens = try normalizedUniqueTokens(allocator, query);
    defer freeStringArrayList(allocator, &query_tokens);
    for (query_tokens.items) |term| {
        for (rec.tags) |tag| {
            if (std.ascii.indexOfIgnoreCase(tag, term) != null) score += 0.75;
        }
        if (std.ascii.indexOfIgnoreCase(rec.domain, term) != null) score += 0.5;
    }

    if (score <= 0.0) return 0.0;
    score += rec.heat;
    score += @as(f64, @floatFromInt(@min(access_count, 20))) * 0.05;
    return score;
}

fn lexicalJaccard(allocator: std.mem.Allocator, a: []const u8, b: []const u8) !f64 {
    var left = try normalizedUniqueTokens(allocator, a);
    defer freeStringArrayList(allocator, &left);
    var right = try normalizedUniqueTokens(allocator, b);
    defer freeStringArrayList(allocator, &right);
    if (left.items.len == 0 or right.items.len == 0) return 0.0;

    var intersection: usize = 0;
    for (left.items) |term| {
        if (containsString(right.items, term)) intersection += 1;
    }
    const union_size = left.items.len + right.items.len - intersection;
    if (union_size == 0) return 0.0;
    return @as(f64, @floatFromInt(intersection)) / @as(f64, @floatFromInt(union_size));
}

fn normalizedUniqueTokens(allocator: std.mem.Allocator, text: []const u8) !std.ArrayList([]const u8) {
    var list: std.ArrayList([]const u8) = .empty;
    errdefer freeStringArrayList(allocator, &list);
    var raw_tokens = std.mem.tokenizeAny(u8, text, " \t\r\n.,;:!?()[]{}<>\"'`/\\|+=*&^%$#@~");
    while (raw_tokens.next()) |raw| {
        const maybe_token = try normalizeTokenAlloc(allocator, raw);
        const token = maybe_token orelse continue;
        if (containsString(list.items, token)) {
            allocator.free(token);
            continue;
        }
        try list.append(allocator, token);
    }
    return list;
}

fn normalizeTokenAlloc(allocator: std.mem.Allocator, raw: []const u8) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    for (raw) |c| {
        if (std.ascii.isAlphanumeric(c)) {
            try out.append(allocator, std.ascii.toLower(c));
        }
    }
    if (out.items.len < 2) {
        out.deinit(allocator);
        return null;
    }
    const token = try out.toOwnedSlice(allocator);
    return token;
}

fn containsString(items: []const []const u8, needle: []const u8) bool {
    for (items) |item| {
        if (std.mem.eql(u8, item, needle)) return true;
    }
    return false;
}

fn fingerprintAlloc(allocator: std.mem.Allocator, text: []const u8) ![]u8 {
    var tokens = try normalizedUniqueTokens(allocator, text);
    defer freeStringArrayList(allocator, &tokens);
    std.mem.sort([]const u8, tokens.items, {}, struct {
        fn lessThan(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lessThan);

    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    for (tokens.items, 0..) |token, index| {
        if (index != 0) try out.writer.writeAll(" ");
        try out.writer.writeAll(token);
    }
    return out.toOwnedSlice();
}

fn redactSensitiveAlloc(allocator: std.mem.Allocator, input: []const u8) !RedactionResult {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    var count: usize = 0;
    var i: usize = 0;
    while (i < input.len) {
        const uri_next = try redactUriAt(&out.writer, input, i);
        if (uri_next) |next| {
            count += 1;
            i = next;
            continue;
        }

        if (sensitiveKeyPrefix(input[i..])) |key_len| {
            try out.writer.writeAll(input[i .. i + key_len]);
            try out.writer.writeAll("[redacted]");
            i = secretValueEnd(input, i + key_len);
            count += 1;
            continue;
        }

        if (tokenPrefix(input, i)) |prefix| {
            try out.writer.writeAll(prefix);
            try out.writer.writeAll("[redacted]");
            i = secretValueEnd(input, i + prefix.len);
            count += 1;
            continue;
        }

        try out.writer.writeAll(input[i .. i + 1]);
        i += 1;
    }
    return .{
        .text = try out.toOwnedSlice(),
        .count = count,
    };
}

fn redactUriAt(writer: *std.Io.Writer, input: []const u8, index: usize) !?usize {
    const prefixes = [_][]const u8{
        "postgresql://",
        "postgres://",
        "mysql://",
        "redis://",
        "http://",
        "https://",
    };
    for (prefixes) |prefix| {
        if (!startsWithIgnoreCase(input[index..], prefix)) continue;
        const authority_start = index + prefix.len;
        const authority_end = authorityEnd(input, authority_start);
        const authority = input[authority_start..authority_end];
        const at_index = std.mem.indexOfScalar(u8, authority, '@') orelse return null;
        const colon_index = std.mem.indexOfScalar(u8, authority[0..at_index], ':') orelse return null;
        if (colon_index >= at_index) return null;
        try writer.writeAll(input[index..authority_start]);
        try writer.writeAll("[credentials-redacted]@");
        try writer.writeAll(authority[at_index + 1 ..]);
        return authority_end;
    }
    return null;
}

fn authorityEnd(input: []const u8, start: usize) usize {
    var i = start;
    while (i < input.len) : (i += 1) {
        const c = input[i];
        if (std.ascii.isWhitespace(c) or c == '"' or c == '\'' or c == ')' or c == ']') break;
        if (c == '/') break;
    }
    return i;
}

fn sensitiveKeyPrefix(input: []const u8) ?usize {
    const keys = [_][]const u8{
        "password=",
        "passwd=",
        "token=",
        "api_key=",
        "apikey=",
        "secret=",
        "access_token=",
        "private_key=",
        "database_url=",
    };
    for (keys) |key| {
        if (startsWithIgnoreCase(input, key)) return key.len;
    }
    return null;
}

fn tokenPrefix(input: []const u8, index: usize) ?[]const u8 {
    if (index != 0 and std.ascii.isAlphanumeric(input[index - 1])) return null;
    const prefixes = [_][]const u8{ "sk-", "ghp_", "github_pat_" };
    for (prefixes) |prefix| {
        if (std.mem.startsWith(u8, input[index..], prefix)) return prefix;
    }
    return null;
}

fn secretValueEnd(input: []const u8, start: usize) usize {
    var i = start;
    while (i < input.len) : (i += 1) {
        const c = input[i];
        if (std.ascii.isWhitespace(c) or c == '"' or c == '\'' or c == '&' or c == ',' or c == ';') break;
    }
    return i;
}

fn startsWithIgnoreCase(haystack: []const u8, prefix: []const u8) bool {
    return haystack.len >= prefix.len and std.ascii.eqlIgnoreCase(haystack[0..prefix.len], prefix);
}

fn selectedContains(selected: []const ScoredMemory, id: []const u8) bool {
    for (selected) |item| {
        if (std.mem.eql(u8, item.id, id)) return true;
    }
    return false;
}

fn relatedContains(related: []const ScoredMemory, id: []const u8) bool {
    for (related) |item| {
        if (std.mem.eql(u8, item.id, id)) return true;
    }
    return false;
}

fn isRelatedToSelection(rec: MemoryRecord, selected: []const ScoredMemory) bool {
    for (selected) |item| {
        if (std.mem.eql(u8, rec.domain, item.domain)) return true;
        if (containsString(rec.supersedes, item.id) or containsString(item.supersedes, rec.id)) return true;
        for (rec.tags) |tag| {
            if (containsString(item.tags, tag)) return true;
        }
    }
    return false;
}

fn detectDomain(path_or_hint: []const u8) []const u8 {
    if (path_or_hint.len == 0) return "global";
    return std.fs.path.basename(path_or_hint);
}

fn classifyIntent(query: []const u8) []const u8 {
    if (std.ascii.indexOfIgnoreCase(query, "why") != null) return "causal";
    if (std.ascii.indexOfIgnoreCase(query, "when") != null) return "temporal";
    if (std.ascii.indexOfIgnoreCase(query, "decided") != null) return "knowledge_update";
    return "general";
}

fn validateWikiPath(path: []const u8) !void {
    if (path.len == 0 or
        std.fs.path.isAbsolute(path) or
        !std.mem.endsWith(u8, path, ".md"))
    {
        return error.InvalidWikiPath;
    }
    if (std.mem.indexOfScalar(u8, path, 0) != null) return error.InvalidWikiPath;
    var parts = std.mem.splitScalar(u8, path, '/');
    while (parts.next()) |part| {
        if (part.len == 0 or std.mem.eql(u8, part, ".") or std.mem.eql(u8, part, "..")) return error.InvalidWikiPath;
    }
}

fn validateName(name: []const u8) !void {
    if (name.len == 0) return error.InvalidName;
    for (name) |c| {
        if (!(std.ascii.isAlphanumeric(c) or c == '-' or c == '_')) return error.InvalidName;
    }
}

fn fileExists(io: std.Io, path: []const u8) bool {
    var file = std.Io.Dir.cwd().openFile(io, path, .{}) catch return false;
    file.close(io);
    return true;
}

fn slugAlloc(allocator: std.mem.Allocator, text: []const u8) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var dash = false;
    for (text) |c| {
        if (std.ascii.isAlphanumeric(c)) {
            try out.append(allocator, std.ascii.toLower(c));
            dash = false;
        } else if (!dash) {
            try out.append(allocator, '-');
            dash = true;
        }
    }
    while (out.items.len > 0 and out.items[out.items.len - 1] == '-') _ = out.pop();
    if (out.items.len == 0) try out.appendSlice(allocator, "untitled");
    return out.toOwnedSlice(allocator);
}

fn toolDescription(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "remember")) return "Store a redacted, duplicate-gated memory in the native Cortex file-backed store.";
    if (std.mem.eql(u8, name, "recall")) return "Retrieve memories with native lexical scoring, supersession filtering, and access logging.";
    if (std.mem.eql(u8, name, "unified_search")) return "Compatibility alias for native recall.";
    if (std.mem.eql(u8, name, "checkpoint")) return "Save or restore a validated native session checkpoint.";
    if (std.mem.eql(u8, name, "detect_domain")) return "Derive a deterministic domain label from a path or hint.";
    if (std.mem.eql(u8, name, "list_domains")) return "List domains present in the native memory store.";
    if (std.mem.eql(u8, name, "memory_stats")) return "Return native memory-store diagnostics.";
    if (std.mem.eql(u8, name, "get_telemetry")) return "Compatibility alias for native memory-store diagnostics.";
    if (std.mem.eql(u8, name, "get_methodology_graph") or
        std.mem.eql(u8, name, "query_workflow_graph") or
        std.mem.eql(u8, name, "navigate_memory"))
    {
        return "Return the native supersession graph.";
    }
    if (std.mem.eql(u8, name, "query_methodology")) return "Return native Cortex context for the current domain.";
    if (std.mem.eql(u8, name, "record_session_end")) return "Acknowledge a native lifecycle event.";
    if (std.mem.eql(u8, name, "wiki_link") or
        std.mem.eql(u8, name, "wiki_purge") or
        std.mem.eql(u8, name, "wiki_rename"))
    {
        return "Compatibility entry retained; this state-changing wiki operation is not implemented natively.";
    }
    if (std.mem.startsWith(u8, name, "wiki_")) return "Operate on the native Cortex Markdown wiki.";
    return "Compatibility entry retained by the native Cortex MCP catalog.";
}

test "wiki path validation rejects traversal" {
    try std.testing.expectError(error.InvalidWikiPath, validateWikiPath("../x.md"));
    try validateWikiPath("notes/x.md");
}

test "memory scoring ranks direct matches" {
    const rec: MemoryRecord = .{
        .content = "The native storage decision is recorded",
        .tags = &.{"decision"},
        .domain = "cortex",
        .heat = 0.5,
    };
    try std.testing.expect(try scoreMemory(std.testing.allocator, "native storage decision", rec, 0) > 4.0);
}

test "redaction removes obvious secret values before persistence" {
    const redacted = try redactSensitiveAlloc(
        std.testing.allocator,
        "connect with data" ++
            "base_url=postgresql://user:" ++
            "pass@example.test/db and api_" ++
            "key=abc123",
    );
    defer std.testing.allocator.free(redacted.text);
    try std.testing.expect(redacted.count >= 2);
    try std.testing.expect(std.mem.indexOf(u8, redacted.text, "pass") == null);
    try std.testing.expect(std.mem.indexOf(u8, redacted.text, "abc123") == null);
    try std.testing.expect(std.mem.indexOf(u8, redacted.text, "[redacted]") != null);
}

test "fuzz: redaction tokenization and scoring are total" {
    try std.testing.fuzz({}, fuzzRedactionTokenizationAndScoring, .{
        .corpus = &.{
            "api_key=secret-value",
            "postgresql://user:pass@example.test/db",
            "sk-test-token",
            "../wiki/traversal.md",
        },
    });
}

fn fuzzRedactionTokenizationAndScoring(_: void, smith: *std.testing.Smith) anyerror!void {
    var buf: [2048]u8 = undefined;
    const len = smith.slice(&buf);
    const input = buf[0..len];

    const redacted = try redactSensitiveAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(redacted.text);

    var tokens = try normalizedUniqueTokens(std.testing.allocator, redacted.text);
    defer freeStringArrayList(std.testing.allocator, &tokens);

    const fingerprint = try fingerprintAlloc(std.testing.allocator, redacted.text);
    defer std.testing.allocator.free(fingerprint);

    const similarity = try lexicalJaccard(std.testing.allocator, input, redacted.text);
    try std.testing.expect(similarity >= 0.0 and similarity <= 1.0);
}

test "lexical jaccard detects near duplicates" {
    const similarity = try lexicalJaccard(
        std.testing.allocator,
        "native cortex stores local memories with zig",
        "Native Cortex stores local memory records with Zig.",
    );
    try std.testing.expect(similarity >= 0.6);
}

test "slug generation is stable" {
    const slug = try slugAlloc(std.testing.allocator, "Native Cortex Rewrite!");
    defer std.testing.allocator.free(slug);
    try std.testing.expectEqualStrings("native-cortex-rewrite", slug);
}

test "mcp notifications do not emit responses" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    const root = try std.fmt.allocPrint(
        std.testing.allocator,
        ".zig-cache/tmp/{s}/notification-store",
        .{tmp.sub_path},
    );
    defer std.testing.allocator.free(root);
    var store = try Store.init(std.testing.allocator, std.testing.io, root);
    defer store.deinit();

    const response = try handleRpc(std.testing.allocator, &store,
        \\{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
    );
    try std.testing.expect(response == null);
}
