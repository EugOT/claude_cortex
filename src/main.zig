const std = @import("std");
const cortex = @import("cortex");

pub fn main(init: std.process.Init) !void {
    try cortex.run(init);
}
