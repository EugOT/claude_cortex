const std = @import("std");
const pkg = @import("build.zig.zon");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const options = b.addOptions();
    options.addOption([]const u8, "version", pkg.version);

    const cortex_mod = b.createModule(.{
        .root_source_file = b.path("src/cortex.zig"),
        .target = target,
        .optimize = optimize,
    });
    cortex_mod.addOptions("build_options", options);

    const exe_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe_mod.addImport("cortex", cortex_mod);

    const exe = b.addExecutable(.{
        .name = "cortex",
        .root_module = exe_mod,
    });
    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);
    const run_step = b.step("run", "Run cortex");
    run_step.dependOn(&run_cmd.step);

    const fmt_check = b.addFmt(.{
        .paths = &.{ "build.zig", "build.zig.zon", "src" },
        .check = true,
    });
    const fmt_step = b.step("fmt", "Check Zig formatting");
    fmt_step.dependOn(&fmt_check.step);

    const unit_tests = b.addTest(.{
        .root_module = cortex_mod,
    });
    const run_unit_tests = b.addRunArtifact(unit_tests);

    const e2e_mod = b.createModule(.{
        .root_source_file = b.path("src/tests.zig"),
        .target = target,
        .optimize = optimize,
    });
    e2e_mod.addImport("cortex", cortex_mod);
    const e2e_tests = b.addTest(.{
        .root_module = e2e_mod,
    });
    const run_e2e_tests = b.addRunArtifact(e2e_tests);

    const test_step = b.step("test", "Run unit and functional tests");
    test_step.dependOn(&run_unit_tests.step);
    test_step.dependOn(&run_e2e_tests.step);

    const check_step = b.step("check", "Compile executable and tests");
    check_step.dependOn(&exe.step);
    check_step.dependOn(&unit_tests.step);
    check_step.dependOn(&e2e_tests.step);

    const install_docs = b.addInstallDirectory(.{
        .source_dir = unit_tests.getEmittedDocs(),
        .install_dir = .prefix,
        .install_subdir = "docs",
    });
    const docs_step = b.step("docs", "Generate Zig docs for the native core");
    docs_step.dependOn(&install_docs.step);

    b.default_step.dependOn(check_step);
}
