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

export interface FollowupMedication {
  name: string;
  dosage: string;
  frequency: string;
  duration: string;
}

export interface FollowupCallRequest {
  appointmentId: string;
  patientId: string;
  patientName: string;
  patientPhone?: string;
  doctorName?: string;
  nextAppointmentAt?: string;
  medications?: FollowupMedication[];
  additionalAdvice?: string[];
  conversationSummary?: string;
}

export interface FollowupCallResponse {
  followupCallId: string;
  status: "queued" | "failed" | "mock" | "completed";
  dialTo: string;
  provider: string;
  dispatchId?: string | null;
  roomName?: string | null;
  dispatchDetail?: string | null;
  followupTaskId?: string | null;
  confirmationMessage: string;
  updatedAt: string;
}

export async function postReminderFollowupCall(
  payload: FollowupCallRequest
): Promise<FollowupCallResponse | null> {
  try {
    const res = await fetch("/api/reminder/followup-call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Reminder API error: ${res.status}`);
    }
    return (await res.json()) as FollowupCallResponse;
  } catch {
    return null;
  }
}

export interface ConsultationTokenResponse {
  token: string;
  url: string;
  roomName: string;
  participantIdentity: string;
  participantName: string;
}

export async function fetchConsultationRoomToken(
  appointmentId: string,
  participantIdentity: string,
  participantName: string
): Promise<ConsultationTokenResponse | null> {
  try {
    const query = new URLSearchParams({
      participantIdentity,
      participantName,
    }).toString();
    const res = await fetch(`/api/lifecycle/consultation/${encodeURIComponent(appointmentId)}/token?${query}`);
    if (!res.ok) throw new Error(`Failed to fetch consultation token (${res.status})`);
    return (await res.json()) as ConsultationTokenResponse;
  } catch {
    return null;
  }
}
