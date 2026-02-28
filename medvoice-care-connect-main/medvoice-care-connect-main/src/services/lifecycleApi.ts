import { productLifecycleStages, type LifecycleStage } from "@/data/mockData";

export interface LifecycleStagesResponse {
  stages: LifecycleStage[];
  eventCount: number;
}

export async function fetchLifecycleStages(): Promise<LifecycleStagesResponse> {
  try {
    const res = await fetch("/api/lifecycle/stages");
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  } catch {
    return {
      stages: productLifecycleStages,
      eventCount: productLifecycleStages.reduce(
        (count, stage) => count + stage.impactedTables.length,
        0
      ),
    };
  }
}

export async function postConsultationStart(appointmentId: string, patientId: string): Promise<void> {
  try {
    await fetch("/api/lifecycle/consultation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appointmentId, patientId }),
    });
  } catch {
    // backend may be down in demo mode
  }
}

export async function postTranscriptBatch(
  appointmentId: string,
  patientId: string,
  messages: Array<{ speaker: "Doctor" | "Patient"; text: string; timestamp: string }>
): Promise<void> {
  try {
    await fetch("/api/lifecycle/consultation/transcript", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appointmentId, patientId, messages }),
    });
  } catch {
    // backend may be down in demo mode
  }
}

export async function postConsultationEnd(appointmentId: string): Promise<void> {
  try {
    await fetch("/api/lifecycle/consultation/end", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appointmentId }),
    });
  } catch {
    // backend may be down in demo mode
  }
}
