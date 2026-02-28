import { describe, expect, it, vi, afterEach } from "vitest";

import { fetchLifecycleStages } from "@/services/lifecycleApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchLifecycleStages", () => {
  it("returns backend payload when api is available", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ stages: [{ id: "a", impactedTables: [], status: "done", title: "x", description: "y" }], eventCount: 1 }), {
        status: 200,
      })
    );

    const result = await fetchLifecycleStages();
    expect(result.eventCount).toBe(1);
    expect(result.stages[0].id).toBe("a");
  });

  it("falls back to local data when api fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const result = await fetchLifecycleStages();
    expect(result.stages.length).toBeGreaterThan(0);
    expect(result.eventCount).toBeGreaterThan(0);
  });
});
