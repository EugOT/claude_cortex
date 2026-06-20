const std = @import("std");
const cortex = @import("cortex");

const TestStore = struct {
    tmp: std.testing.TmpDir,
    root: []u8,
    store: cortex.Store,

    fn init() !TestStore {
        var tmp = std.testing.tmpDir(.{});
        errdefer tmp.cleanup();

        const root = try std.fmt.allocPrint(std.testing.allocator, ".zig-cache/tmp/{s}/store", .{tmp.sub_path});
        errdefer std.testing.allocator.free(root);

        const store = try cortex.Store.init(std.testing.allocator, std.testing.io, root);
        return .{
            .tmp = tmp,
            .root = root,
            .store = store,
        };
    }

    fn deinit(self: *TestStore) void {
        self.store.deinit();
        std.testing.allocator.free(self.root);
        self.tmp.cleanup();
        self.* = undefined;
    }
};

test "functional remember recall stats round trip" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const remembered = try store.remember(.{
        .content = "Native Cortex keeps recall in Zig.",
        .tags = &.{ "native", "zig" },
        .domain = "claude-cortex",
        .force = true,
    });
    defer std.testing.allocator.free(remembered);
    try std.testing.expect(std.mem.indexOf(u8, remembered, "\"stored\":true") != null);

    const recalled = try store.recall(.{ .query = "recall Zig", .domain = "claude-cortex" });
    defer std.testing.allocator.free(recalled);
    try std.testing.expect(std.mem.indexOf(u8, recalled, "Native Cortex keeps recall") != null);

    const recalled_zero = try store.recall(.{ .query = "recall Zig", .domain = "claude-cortex", .max_results = 0 });
    defer std.testing.allocator.free(recalled_zero);
    var zero_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, recalled_zero, .{});
    defer zero_json.deinit();
    try std.testing.expect(zero_json.value == .object);
    const zero_count = zero_json.value.object.get("count") orelse return error.MissingCountField;
    try std.testing.expect(zero_count == .integer);
    try std.testing.expectEqual(@as(i64, 0), zero_count.integer);
    const zero_memories = zero_json.value.object.get("memories") orelse return error.MissingMemoriesField;
    try std.testing.expect(zero_memories == .array);
    try std.testing.expectEqual(@as(usize, 0), zero_memories.array.items.len);

    const stats = try store.memoryStats();
    defer std.testing.allocator.free(stats);
    var stats_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, stats, .{});
    defer stats_json.deinit();
    try std.testing.expect(stats_json.value == .object);
    const total_memories = stats_json.value.object.get("total_memories") orelse return error.MissingTotalMemoriesField;
    try std.testing.expect(total_memories == .integer);
    try std.testing.expectEqual(@as(i64, 1), total_memories.integer);
}

test "functional wiki write read list" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const written = try store.wikiWrite("notes/native.md", "# Native\n", "create");
    defer std.testing.allocator.free(written);
    try std.testing.expect(std.mem.indexOf(u8, written, "\"created\":true") != null);

    const read = try store.wikiRead("notes/native.md");
    defer std.testing.allocator.free(read);
    try std.testing.expect(std.mem.indexOf(u8, read, "# Native") != null);

    const appended_first = try store.wikiWrite("notes/append.md", "first", "append");
    defer std.testing.allocator.free(appended_first);
    const appended_second = try store.wikiWrite("notes/append.md", "second", "append");
    defer std.testing.allocator.free(appended_second);
    const appended_read = try store.wikiRead("notes/append.md");
    defer std.testing.allocator.free(appended_read);
    var appended_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, appended_read, .{});
    defer appended_json.deinit();
    try std.testing.expect(appended_json.value == .object);
    const appended_content = appended_json.value.object.get("content") orelse return error.MissingContentField;
    try std.testing.expect(appended_content == .string);
    try std.testing.expectEqualStrings("first\nsecond", appended_content.string);

    const list = try store.wikiList();
    defer std.testing.allocator.free(list);
    try std.testing.expect(std.mem.indexOf(u8, list, "notes/native.md") != null);
}

test "functional duplicate remembers receive distinct ids" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const first = try store.remember(.{ .content = "same millisecond candidate", .force = true });
    defer std.testing.allocator.free(first);
    const second = try store.remember(.{ .content = "same millisecond candidate", .force = true });
    defer std.testing.allocator.free(second);

    var first_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, first, .{});
    defer first_json.deinit();
    var second_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, second, .{});
    defer second_json.deinit();
    try std.testing.expect(first_json.value == .object);
    try std.testing.expect(second_json.value == .object);
    const first_id = first_json.value.object.get("memory_id") orelse return error.MissingMemoryIdField;
    const second_id = second_json.value.object.get("memory_id") orelse return error.MissingMemoryIdField;
    try std.testing.expect(first_id == .string);
    try std.testing.expect(second_id == .string);
    try std.testing.expect(!std.mem.eql(u8, first_id.string, second_id.string));
}

test "functional write gate rejects near duplicates unless forced" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const first = try store.remember(.{
        .content = "Native Cortex stores scientific retrieval evidence locally.",
        .domain = "safety",
    });
    defer std.testing.allocator.free(first);
    try std.testing.expect(std.mem.indexOf(u8, first, "\"stored\":true") != null);

    const rejected = try store.remember(.{
        .content = "native cortex stores scientific retrieval evidence locally",
        .domain = "safety",
    });
    defer std.testing.allocator.free(rejected);
    try std.testing.expect(std.mem.indexOf(u8, rejected, "\"stored\":false") != null);
    try std.testing.expect(std.mem.indexOf(u8, rejected, "near_duplicate") != null);

    const forced = try store.remember(.{
        .content = "native cortex stores scientific retrieval evidence locally",
        .domain = "safety",
        .force = true,
    });
    defer std.testing.allocator.free(forced);
    try std.testing.expect(std.mem.indexOf(u8, forced, "\"stored\":true") != null);
}

test "functional secret redaction happens before recall" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const remembered = try store.remember(.{
        .content = "Credential handling note: api_" ++
            "key=abc123 must never be persisted.",
        .domain = "security",
        .force = true,
    });
    defer std.testing.allocator.free(remembered);
    try std.testing.expect(std.mem.indexOf(u8, remembered, "\"redacted\":true") != null);

    const recalled = try store.recall(.{ .query = "credential persisted", .domain = "security" });
    defer std.testing.allocator.free(recalled);
    try std.testing.expect(std.mem.indexOf(u8, recalled, "api_key=[redacted]") != null);
    try std.testing.expect(std.mem.indexOf(u8, recalled, "abc123") == null);
}

test "functional supersession hides old memories and exposes related context" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const old_memory = try store.remember(.{
        .content = "Old recall used substring-only ranking.",
        .tags = &.{"retrieval"},
        .domain = "cortex",
        .force = true,
    });
    defer std.testing.allocator.free(old_memory);
    var old_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, old_memory, .{});
    defer old_json.deinit();
    const old_id = old_json.value.object.get("memory_id") orelse return error.MissingMemoryIdField;
    try std.testing.expect(old_id == .string);

    const new_memory = try store.remember(.{
        .content = "New recall uses lexical Jaccard ranking with explicit supersession.",
        .tags = &.{"retrieval"},
        .domain = "cortex",
        .supersedes = &.{old_id.string},
        .force = true,
    });
    defer std.testing.allocator.free(new_memory);
    var new_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, new_memory, .{});
    defer new_json.deinit();
    const new_id = new_json.value.object.get("memory_id") orelse return error.MissingMemoryIdField;
    try std.testing.expect(new_id == .string);

    const default_recall = try store.recall(.{ .query = "recall ranking", .domain = "cortex" });
    defer std.testing.allocator.free(default_recall);
    var default_json = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, default_recall, .{});
    defer default_json.deinit();
    const default_memories = default_json.value.object.get("memories") orelse return error.MissingMemoriesField;
    try std.testing.expect(default_memories == .array);
    var found_new = false;
    for (default_memories.array.items) |item| {
        try std.testing.expect(item == .object);
        const item_id = item.object.get("id") orelse return error.MissingMemoryIdField;
        try std.testing.expect(item_id == .string);
        if (std.mem.eql(u8, item_id.string, new_id.string)) found_new = true;
        try std.testing.expect(!std.mem.eql(u8, item_id.string, old_id.string));
    }
    try std.testing.expect(found_new);

    const full_recall = try store.recall(.{
        .query = "substring ranking",
        .domain = "cortex",
        .include_superseded = true,
        .include_related = true,
    });
    defer std.testing.allocator.free(full_recall);
    try std.testing.expect(std.mem.indexOf(u8, full_recall, old_id.string) != null);
    try std.testing.expect(std.mem.indexOf(u8, full_recall, "\"related_count\"") != null);

    const graph = try store.memoryGraph();
    defer std.testing.allocator.free(graph);
    try std.testing.expect(std.mem.indexOf(u8, graph, "supersedes") != null);
    try std.testing.expect(std.mem.indexOf(u8, graph, old_id.string) != null);

    const domains = try store.listDomains();
    defer std.testing.allocator.free(domains);
    try std.testing.expect(std.mem.indexOf(u8, domains, "cortex") != null);

    const stats = try store.memoryStats();
    defer std.testing.allocator.free(stats);
    try std.testing.expect(std.mem.indexOf(u8, stats, "\"access_events\":") != null);
    try std.testing.expect(std.mem.indexOf(u8, stats, "\"total_relationships\":1") != null);
}

test "functional checkpoint save restore" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    const saved = try store.checkpoint("save", "session-a", "{\"next\":\"test\"}");
    defer std.testing.allocator.free(saved);
    try std.testing.expect(std.mem.indexOf(u8, saved, "\"saved\":true") != null);

    const restored = try store.checkpoint("restore", "session-a", "{}");
    defer std.testing.allocator.free(restored);
    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, restored, .{});
    defer parsed.deinit();
    try std.testing.expect(parsed.value == .object);
    const content = parsed.value.object.get("content") orelse return error.MissingContentField;
    try std.testing.expect(content == .string);
    try std.testing.expectEqualStrings("{\"next\":\"test\"}", content.string);
}

test "mcp tool dispatcher handles remember and recall" {
    var fixture = try TestStore.init();
    defer fixture.deinit();
    const store = &fixture.store;

    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator,
        \\{"content":"MCP remembers through the native dispatcher.","domain":"mcp"}
    , .{});
    defer parsed.deinit();
    const remembered = try cortex.handleToolJson(std.testing.allocator, store, "remember", parsed.value);
    defer std.testing.allocator.free(remembered);
    try std.testing.expect(std.mem.indexOf(u8, remembered, "\"stored\":true") != null);

    var query = try std.json.parseFromSlice(std.json.Value, std.testing.allocator,
        \\{"query":"native dispatcher","domain":"mcp"}
    , .{});
    defer query.deinit();
    const recalled = try cortex.handleToolJson(std.testing.allocator, store, "recall", query.value);
    defer std.testing.allocator.free(recalled);
    try std.testing.expect(std.mem.indexOf(u8, recalled, "native dispatcher") != null);
}
