import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSuggestedQuestions } from "@/services/consultationApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchSuggestedQuestions", () => {
  const payload = {
    appointmentId: "apt-1",
    patientId: "pat-1",
    transcript: [{ speaker: "Patient" as const, text: "J'ai mal a la gorge", timestamp: "00:10" }],
  };

  it("uses backend response when available", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ questions: ["Depuis quand ?"], redFlags: [], askedTopics: ["douleur"] }),
        { status: 200 }
      )
    );
    const result = await fetchSuggestedQuestions(payload);
    expect(result.questions[0]).toBe("Depuis quand ?");
  });

  it("falls back when backend is unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const result = await fetchSuggestedQuestions(payload);
    expect(result.questions.length).toBeGreaterThan(0);
  });
});
