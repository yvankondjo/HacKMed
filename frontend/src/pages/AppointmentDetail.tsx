import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { enUS } from "date-fns/locale";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Play,
  Square,
  PhoneCall,
  Plus,
  Trash2,
  AlertTriangle,
  Send,
  Stethoscope,
  Loader2,
  Radio,
} from "lucide-react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useRoomContext,
} from "@livekit/components-react";
import { Track, RoomEvent } from "livekit-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { type Medication } from "@/data/mockData";
import { useTranscriptSocket, type TranscriptEntry } from "@/hooks/useTranscriptSocket";
import { fetchConsultationSummary, fetchSuggestedQuestions } from "@/services/consultationApi";
import { fetchAppointmentDetail, type DashboardAppointmentDetail } from "@/services/careDataApi";
import {
  fetchConsultationRoomToken,
  postReminderFollowupCall,
  postConsultationEnd,
  postConsultationStart,
  postTranscriptBatch,
  postPrescriptionSend,
} from "@/services/lifecycleApi";

type SoapNote = {
  subjective?: string;
  objective?: string;
  assessment?: string;
  plan?: string;
};

type SoapPayload = {
  soap?: SoapNote;
  meds_mentioned?: unknown;
  followups?: unknown;
  enhanced_transcript?: unknown;
};

type ConsultationContextPayload = {
  appointment_id?: string;
  patient_id?: string;
  appointment_motif?: string;
  patient_name?: string;
  patient_age?: number | null;
  allergies?: string[];
  antecedents?: string[];
  history_highlights?: string[];
  recent_call_highlights?: string[];
};

function asStringArray(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  return input
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

const DEFAULT_PRESCRIPTION_RECIPIENT = "yvankondjo8@gmail.com";

function LiveKitTranscriptListener({
  onTranscript,
  onSuggestions,
  onSoap,
  shouldRequestEnd,
  consultationContext,
}: {
  onTranscript: (entry: TranscriptEntry) => void;
  onSuggestions: (questions: string[], redFlags: string[]) => void;
  onSoap: (soapData: SoapPayload) => void;
  shouldRequestEnd: boolean;
  consultationContext: ConsultationContextPayload | null;
}) {
  const room = useRoomContext();
  const { localParticipant } = room;
  const hasSentEndCmd = useRef(false);
  const hasSentRoleCmd = useRef(false);
  const sentContextPayloadRef = useRef<string>("");

  useEffect(() => {
    if (shouldRequestEnd && localParticipant && !hasSentEndCmd.current) {
      hasSentEndCmd.current = true;
      const payload = JSON.stringify({ type: "end_session" });

      // New LiveKit text stream API (matches Python `register_text_stream_handler`).
      localParticipant.sendText(payload, { topic: "clinic.control" }).catch((e) => {
        console.error("Agent text stream error:", e);
      });

      // Keep data packet fallback for compatibility with older agents.
      const enc = new TextEncoder();
      const data = enc.encode(payload);
      localParticipant.publishData(data, { topic: "clinic.control" }).catch((e) => {
        console.error("Agent data channel error:", e);
      });
    }
    if (!shouldRequestEnd) {
      hasSentEndCmd.current = false;
    }
  }, [shouldRequestEnd, localParticipant]);

  useEffect(() => {
    if (!localParticipant || hasSentRoleCmd.current) return;
    hasSentRoleCmd.current = true;
    const payload = JSON.stringify({
      type: "set_role",
      identity: localParticipant.identity,
      role: "doctor",
    });

    localParticipant.sendText(payload, { topic: "clinic.control" }).catch((e) => {
      console.error("Failed to send role via text stream:", e);
    });

    const enc = new TextEncoder();
    const data = enc.encode(payload);
    localParticipant.publishData(data, { topic: "clinic.control" }).catch((e) => {
      console.error("Failed to send role via data channel:", e);
    });
  }, [localParticipant]);

  useEffect(() => {
    if (!localParticipant || !consultationContext) return;
    const payload = JSON.stringify({
      type: "set_context",
      identity: localParticipant.identity,
      context: consultationContext,
    });
    if (sentContextPayloadRef.current === payload) return;
    sentContextPayloadRef.current = payload;

    localParticipant.sendText(payload, { topic: "clinic.control" }).catch((e) => {
      console.error("Failed to send context via text stream:", e);
    });

    const enc = new TextEncoder();
    const data = enc.encode(payload);
    localParticipant.publishData(data, { topic: "clinic.control" }).catch((e) => {
      console.error("Failed to send context via data channel:", e);
    });
  }, [localParticipant, consultationContext]);
  
  useEffect(() => {
    if (!room) return;

    const handleDecodedPayload = (topic: string | undefined, rawPayload: string) => {
      if (!rawPayload.trim()) return;
      try {
        const msg = JSON.parse(rawPayload) as Record<string, unknown>;
        if (topic === "clinic.transcript" && typeof msg.text === "string") {
          let transcriptTs = format(new Date(), "HH:mm:ss");
          const rawTs = msg.timestamp;
          if (typeof rawTs === "number" && Number.isFinite(rawTs)) {
            transcriptTs = format(new Date(rawTs * 1000), "HH:mm:ss");
          } else if (typeof rawTs === "string" && rawTs.trim()) {
            const numericTs = Number(rawTs);
            if (Number.isFinite(numericTs) && rawTs.trim() !== "") {
              transcriptTs = format(new Date(numericTs * 1000), "HH:mm:ss");
            } else {
              const parsedTs = new Date(rawTs);
              if (!Number.isNaN(parsedTs.getTime())) {
                transcriptTs = format(parsedTs, "HH:mm:ss");
              }
            }
          }
          onTranscript({
            speaker: msg.speaker === "Doctor" ? "Doctor" : "Patient",
            text: msg.text,
            timestamp: transcriptTs,
          });
        } else if (topic === "clinic.suggestions") {
          onSuggestions(asStringArray(msg.questions), asStringArray(msg.missing_info));
        } else if (topic === "clinic.soap") {
          onSoap(msg as SoapPayload);
        }
      } catch (err) {
        console.error("Failed to parse LiveKit payload", err);
      }
    };

    const handleData = (
      payload: Uint8Array,
      _participant: unknown,
      _kind: unknown,
      topic?: string
    ) => {
      const decoder = new TextDecoder();
      handleDecodedPayload(topic, decoder.decode(payload));
    };

    const bindTextStream = (topic: string) => {
      room.registerTextStreamHandler(topic, (reader) => {
        void reader
          .readAll()
          .then((text) => handleDecodedPayload(topic, text))
          .catch((err) => {
            console.error(`Failed to read LiveKit text stream for topic=${topic}`, err);
          });
      });
    };

    bindTextStream("clinic.transcript");
    bindTextStream("clinic.suggestions");
    bindTextStream("clinic.soap");
    room.on(RoomEvent.DataReceived, handleData);
    
    return () => {
      room.unregisterTextStreamHandler("clinic.transcript");
      room.unregisterTextStreamHandler("clinic.suggestions");
      room.unregisterTextStreamHandler("clinic.soap");
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room, onTranscript, onSuggestions, onSoap]);

  return null;
}

function formatSoapSummary(soapData: SoapPayload | null): string {
  if (!soapData) return "No summary available.";
  const soap = soapData.soap;
  if (!soap || typeof soap !== "object") {
    return "Consultation ended. Structured SOAP note was not available.";
  }

  const chunks: string[] = [];
  if (soap.subjective) chunks.push(`Subjective: ${soap.subjective}`);
  if (soap.objective) chunks.push(`Objective: ${soap.objective}`);
  if (soap.assessment) chunks.push(`Assessment: ${soap.assessment}`);
  if (soap.plan) chunks.push(`Plan: ${soap.plan}`);
  return chunks.join(" ");
}

function extractSoapMedications(soapData: SoapPayload | null): Medication[] {
  return asStringArray(soapData?.meds_mentioned)
    .map((name) => ({
      name,
      dosage: "",
      frequency: "",
      duration: "",
    }));
}

export default function AppointmentDetail() {
  const SUGGESTIONS_MIN_DISPLAY_MS = 10_000;
  const { id } = useParams();
  const navigate = useNavigate();
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const lastSyncedTranscriptRef = useRef(0);
  const suggestionsRequestSeqRef = useRef(0);
  const suggestionSwapTimerRef = useRef<number | null>(null);
  const lastSuggestionAppliedAtRef = useRef(0);
  const queuedSuggestionsRef = useRef<{ questions: string[]; flags: string[] } | null>(null);
  const currentSuggestionsRef = useRef<{ questions: string[]; flags: string[] }>({
    questions: [],
    flags: [],
  });
  const [detail, setDetail] = useState<DashboardAppointmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [detailError, setDetailError] = useState<string | null>(null);

  // ─── Consultation state ───
  const [consultationStarted, setConsultationStarted] = useState(false);
  const [consultationEnded, setConsultationEnded] = useState(false);
  const [endingRequested, setEndingRequested] = useState(false);

  // ─── AI / Prescription state ───
  const [aiSummary, setAiSummary] = useState<string>("");
  const [soapPayload, setSoapPayload] = useState<SoapPayload | null>(null);
  const [detectedSymptoms, setDetectedSymptoms] = useState<string[]>([]);
  const [diagnoses, setDiagnoses] = useState<string[]>([]);
  const [prescription, setPrescription] = useState<Medication[]>([]);
  const [contextSignals, setContextSignals] = useState<string[]>([]);
  const [showPrescription, setShowPrescription] = useState(false);
  const [validated, setValidated] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [redFlags, setRedFlags] = useState<string[]>([]);
  const [isLaunchingReminder, setIsLaunchingReminder] = useState(false);
  const [sendingPrescription, setSendingPrescription] = useState(false);

  // ─── LiveKit state ───
  const [token, setToken] = useState<string | null>(null);
  const [liveKitUrl, setLiveKitUrl] = useState<string | null>(null);
  const soapFallbackTimerRef = useRef<number | null>(null);
  const summaryFinalizedRef = useRef(false);

  // ─── WebSocket transcript ───
  const {
    connected: wsConnected,
    transcript,
    connect: wsConnect,
    disconnect: wsDisconnect,
    injectMessage,
    getSerializableTranscript,
    clearTranscript,
  } = useTranscriptSocket({
    // With LiveKit, we might not strictly need this WS connection anymore if we stream via data channels
    // However, to keep using your existing `/api/lifecycle/consultation/transcript` backend polling
    // we could keep the hook as a state bucket, or adjust it later.
    url: null,
  });

  const clearSoapFallbackTimer = useCallback(() => {
    if (soapFallbackTimerRef.current !== null) {
      window.clearTimeout(soapFallbackTimerRef.current);
      soapFallbackTimerRef.current = null;
    }
  }, []);

  const clearSuggestionSwapTimer = useCallback(() => {
    if (suggestionSwapTimerRef.current !== null) {
      window.clearTimeout(suggestionSwapTimerRef.current);
      suggestionSwapTimerRef.current = null;
    }
  }, []);

  const applySuggestionUpdate = useCallback(
    (questions: string[], flags: string[]) => {
      const normalizedQuestions = Array.from(
        new Set((questions || []).map((item) => String(item || "").trim()).filter(Boolean))
      );
      const normalizedFlags = Array.from(
        new Set((flags || []).map((item) => String(item || "").trim()).filter(Boolean))
      );

      if (normalizedQuestions.length === 0 && normalizedFlags.length === 0) {
        return;
      }

      const arraysEqual = (left: string[], right: string[]) =>
        left.length === right.length && left.every((value, idx) => value === right[idx]);

      const current = currentSuggestionsRef.current;
      if (
        arraysEqual(normalizedQuestions, current.questions) &&
        arraysEqual(normalizedFlags, current.flags)
      ) {
        return;
      }

      const now = Date.now();
      const elapsed = now - lastSuggestionAppliedAtRef.current;
      const canReplaceImmediately =
        current.questions.length === 0 && current.flags.length === 0
          ? true
          : elapsed >= SUGGESTIONS_MIN_DISPLAY_MS;

      if (canReplaceImmediately) {
        clearSuggestionSwapTimer();
        queuedSuggestionsRef.current = null;
        currentSuggestionsRef.current = {
          questions: normalizedQuestions,
          flags: normalizedFlags,
        };
        setSuggestedQuestions(normalizedQuestions);
        setRedFlags(normalizedFlags);
        lastSuggestionAppliedAtRef.current = now;
        return;
      }

      queuedSuggestionsRef.current = {
        questions: normalizedQuestions,
        flags: normalizedFlags,
      };

      if (suggestionSwapTimerRef.current !== null) return;

      const delay = Math.max(250, SUGGESTIONS_MIN_DISPLAY_MS - elapsed);
      suggestionSwapTimerRef.current = window.setTimeout(() => {
        suggestionSwapTimerRef.current = null;
        const queued = queuedSuggestionsRef.current;
        if (!queued) return;
        queuedSuggestionsRef.current = null;

        const latestCurrent = currentSuggestionsRef.current;
        const alreadyDisplayed =
          arraysEqual(queued.questions, latestCurrent.questions) &&
          arraysEqual(queued.flags, latestCurrent.flags);
        if (alreadyDisplayed) return;

        currentSuggestionsRef.current = queued;
        setSuggestedQuestions(queued.questions);
        setRedFlags(queued.flags);
        lastSuggestionAppliedAtRef.current = Date.now();
      }, delay);
    },
    [SUGGESTIONS_MIN_DISPLAY_MS, clearSuggestionSwapTimer]
  );

  useEffect(() => {
    return () => {
      clearSoapFallbackTimer();
      clearSuggestionSwapTimer();
    };
  }, [clearSoapFallbackTimer, clearSuggestionSwapTimer]);

  useEffect(() => {
    let active = true;
    const run = async () => {
      if (!id) {
        setDetail(null);
        setDetailLoading(false);
        setDetailError("Missing appointment id.");
        return;
      }
      setDetailLoading(true);
      setDetailError(null);
      const value = await fetchAppointmentDetail(id);
      if (!active) return;
      if (!value) {
        setDetail(null);
        setDetailError("Appointment not found.");
      } else {
        setDetail(value);
      }
      setDetailLoading(false);
    };
    void run();
    return () => {
      active = false;
    };
  }, [id]);

  const appointment = detail?.appointment ?? null;
  const patient = detail?.patient ?? null;
  const history = useMemo(() => detail?.history ?? [], [detail?.history]);
  const relatedCalls = useMemo(() => detail?.calls ?? [], [detail?.calls]);

  const consultationContext = useMemo<ConsultationContextPayload | null>(() => {
    if (!appointment || !patient) return null;
    const patientName = `${patient.firstName} ${patient.lastName}`.trim();
    const patientAge = patient.dateOfBirth
      ? Math.floor(
          (Date.now() - new Date(patient.dateOfBirth).getTime()) /
            (365.25 * 24 * 60 * 60 * 1000)
        )
      : null;

    const historyHighlights = history
      .map((item) => {
        const motif = String(item.motif || "").trim();
        const summary = String(item.summary || "").trim();
        const composed = [motif, summary].filter(Boolean).join(": ").trim();
        return composed ? composed.slice(0, 220) : "";
      })
      .filter(Boolean)
      .slice(0, 4);

    const recentCallHighlights = relatedCalls
      .map((call) => {
        const summary = String(call.summary || "").trim();
        if (summary) return summary.slice(0, 220);
        return String(call.motif || "").trim().slice(0, 220);
      })
      .filter(Boolean)
      .slice(0, 4);

    return {
      appointment_id: appointment.id,
      patient_id: patient.id,
      appointment_motif: appointment.motif,
      patient_name: patientName,
      patient_age: patientAge,
      allergies: patient.allergies || [],
      antecedents: patient.antecedents || [],
      history_highlights: historyHighlights,
      recent_call_highlights: recentCallHighlights,
    };
  }, [appointment, patient, history, relatedCalls]);

  const hasAllergyConflict =
    !!patient?.allergies.some((a) =>
      ["penicillin", "amoxicillin"].some((needle) =>
        a.toLowerCase().includes(needle)
      )
    ) &&
    prescription.some((m) => {
      const name = m.name.toLowerCase();
      return name.includes("amoxicilline") || name.includes("amoxicillin");
    });

  useEffect(() => {
    if (!consultationEnded) return;
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [consultationEnded, transcript]);

  useEffect(() => {
    if (consultationEnded) return;
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [consultationEnded, transcript]);

  useEffect(() => {
    if (!consultationStarted || consultationEnded) return;
    if (!appointment || !patient) return;
    if (transcript.length <= lastSyncedTranscriptRef.current) return;
    const unsynced = transcript.slice(lastSyncedTranscriptRef.current);
    lastSyncedTranscriptRef.current = transcript.length;

    void postTranscriptBatch(appointment.id, patient.id, unsynced);
  }, [consultationStarted, consultationEnded, transcript, appointment, patient]);

  useEffect(() => {
    if (!consultationStarted || consultationEnded) return;
    if (!appointment || !patient) return;
    if (transcript.length < 3) return;

    const requestSeq = ++suggestionsRequestSeqRef.current;
    const timer = window.setTimeout(async () => {
      const response = await fetchSuggestedQuestions({
        appointmentId: appointment.id,
        patientId: patient.id,
        transcript,
      });
      if (requestSeq !== suggestionsRequestSeqRef.current) return;
      applySuggestionUpdate(response.questions || [], response.redFlags || []);
    }, 1200);

    return () => {
      window.clearTimeout(timer);
    };
  }, [
    consultationStarted,
    consultationEnded,
    appointment,
    patient,
    transcript,
    applySuggestionUpdate,
  ]);

  const startConsultation = async () => {
    if (!appointment || !patient) return;
    setConsultationEnded(false);
    setEndingRequested(false);
    setSummaryLoading(false);
    setAiSummary("");
    setSoapPayload(null);
    setDetectedSymptoms([]);
    setDiagnoses([]);
    setPrescription([]);
    setContextSignals([]);
    setShowPrescription(false);
    setValidated(false);
    clearSuggestionSwapTimer();
    queuedSuggestionsRef.current = null;
    currentSuggestionsRef.current = { questions: [], flags: [] };
    lastSuggestionAppliedAtRef.current = 0;
    setSuggestedQuestions([]);
    setRedFlags([]);
    setConsultationStarted(true);
    summaryFinalizedRef.current = false;
    clearSoapFallbackTimer();
    lastSyncedTranscriptRef.current = 0;
    clearTranscript();

    const tokenData = await fetchConsultationRoomToken(
      appointment.id,
      `doc-${appointment.id}`,
      "Doctor"
    );
    if (!tokenData) {
      console.error("Failed to fetch LiveKit consultation token.");
      toast.error("Unable to start consultation: Voice agent token unavailable.");
      setConsultationStarted(false);
      return;
    }
    setToken(tokenData.token);
    setLiveKitUrl(tokenData.url);

    wsConnect();
    void postConsultationStart(appointment.id, patient.id);
  };

  const finalizeConsultationOutputs = useCallback(
    async (payload: SoapPayload | null) => {
      if (!appointment || !patient) return;
      const payloadObj =
        payload && typeof payload === "object" ? (payload as Record<string, unknown>) : null;
      const hasStructuredSoap = Boolean(payloadObj?.soap && typeof payloadObj.soap === "object");
      const hasAdjudicatedTranscript =
        Array.isArray(payloadObj?.enhanced_transcript) &&
        (payloadObj.enhanced_transcript as unknown[]).length > 0;
      const hasSignalLists =
        asStringArray(payloadObj?.meds_mentioned).length > 0 ||
        asStringArray(payloadObj?.followups).length > 0 ||
        asStringArray(payloadObj?.safety_checks).length > 0;
      const isProvisionalFallback = !hasStructuredSoap && !hasAdjudicatedTranscript && !hasSignalLists;

      // Real SOAP payloads lock the flow. Fallback payloads remain provisional so
      // late adjudicated SOAP can still replace the UI.
      if (summaryFinalizedRef.current) return;
      if (!isProvisionalFallback) {
        summaryFinalizedRef.current = true;
      }
      clearSoapFallbackTimer();
      setSoapPayload(payload);

      const fallbackTranscript = getSerializableTranscript();
      const transcriptForSummary = fallbackTranscript;
      const soapForSummary =
        payload && typeof payload === "object"
          ? {
              ...(payload.soap && typeof payload.soap === "object" ? payload.soap : {}),
              meds_mentioned: asStringArray(payload.meds_mentioned),
              followups: asStringArray(payload.followups),
              safety_checks: asStringArray((payload as Record<string, unknown>).safety_checks),
            }
          : {};
      try {
        const result = await fetchConsultationSummary({
          appointmentId: appointment.id,
          patientId: patient.id,
          transcript: transcriptForSummary,
          soap: soapForSummary,
        });
        setAiSummary(result.summary || formatSoapSummary(payload));
        setDetectedSymptoms(result.detectedSymptoms || []);
        setDiagnoses(result.diagnoses || []);
        setContextSignals(result.contextSignals || []);
        setPrescription(result.prescription?.medications || extractSoapMedications(payload));
      } catch (err) {
        console.error("Failed to generate consultation summary from backend:", err);
        setAiSummary(formatSoapSummary(payload));
        setPrescription(extractSoapMedications(payload));
      } finally {
        setShowPrescription(true);
        setSummaryLoading(false);
        setEndingRequested(false);
        setConsultationEnded(true);
        wsDisconnect();
      }
    },
    [appointment, patient, getSerializableTranscript, wsDisconnect, clearSoapFallbackTimer]
  );

  const endConsultation = async () => {
    if (!appointment) return;
    if (endingRequested || consultationEnded) return;
    setEndingRequested(true);
    setSummaryLoading(true);
    summaryFinalizedRef.current = false;
    clearSoapFallbackTimer();
    soapFallbackTimerRef.current = window.setTimeout(() => {
      // Keep UX unblocked if SOAP packet is delayed/lost.
      void finalizeConsultationOutputs({});
    }, 30000);

    try {
      await postConsultationEnd(appointment.id);
    } catch (err) {
      console.error("Failed to end consultation properly:", err);
      // Fall back to summary generation from transcript-only context.
      void finalizeConsultationOutputs({});
    }
  };

  const handleSoap = useCallback(
    async (payload: SoapPayload) => {
      await finalizeConsultationOutputs(payload);
    },
    [finalizeConsultationOutputs]
  );

  const launchReminderCall = useCallback(async () => {
    if (!appointment || !patient) return;
    if (isLaunchingReminder) return;
    setIsLaunchingReminder(true);
    try {
      const response = await postReminderFollowupCall({
        appointmentId: appointment.id,
        patientId: patient.id,
        patientName: `${patient.firstName} ${patient.lastName}`.trim(),
        patientPhone: patient.phone || undefined,
        doctorName: appointment.doctor,
        nextAppointmentAt: appointment.startsAt,
        medications: prescription,
        additionalAdvice: asStringArray(soapPayload?.followups),
        conversationSummary: aiSummary || undefined,
      });

      if (!response) {
        toast.error("Failed to launch outbound follow-up call.");
        return;
      }

      if (response.status === "failed") {
        toast.error(`Follow-up dispatch failed: ${response.dispatchDetail || "Unknown reason"}`);
      } else if (response.status === "mock") {
        toast.warning(`Mock follow-up dispatch: ${response.confirmationMessage}`);
      } else {
        toast.success(
          `Follow-up call queued to ${response.dialTo}${response.dispatchId ? ` (dispatch ${response.dispatchId})` : ""}`
        );
      }

      const refreshed = await fetchAppointmentDetail(appointment.id);
      if (refreshed) setDetail(refreshed);
    } finally {
      setIsLaunchingReminder(false);
    }
  }, [
    appointment,
    patient,
    isLaunchingReminder,
    prescription,
    soapPayload,
    aiSummary,
  ]);

  const handleValidateAndSend = async () => {
    if (!appointment || !patient) return;
    if (sendingPrescription) return;
    const recipientEmail =
      (import.meta.env.VITE_PRESCRIPTION_RECIPIENT_EMAIL || DEFAULT_PRESCRIPTION_RECIPIENT).trim() ||
      DEFAULT_PRESCRIPTION_RECIPIENT;
    setSendingPrescription(true);
    try {
      const response = await postPrescriptionSend({
        appointmentId: appointment.id,
        patientId: patient.id,
        patientName: `${patient.firstName} ${patient.lastName}`.trim(),
        doctorName: appointment.doctor,
        medications: prescription,
        patientEmail: recipientEmail,
        additionalAdvice: asStringArray(soapPayload?.followups),
        transcript: transcript,
      });

      if (!response) {
        toast.error("Failed to connect to the prescription service.");
        return;
      }

      if (response.ok) {
        toast.success(`Prescription sent successfully to ${response.to || recipientEmail}`);
        setValidated(true);
      } else {
        toast.error(`Failed to send prescription: ${response.detail || "Unknown error"}`);
      }
    } finally {
      setSendingPrescription(false);
    }
  };

  const applySuggestedQuestion = (question: string) => {
    injectMessage({
      speaker: "Doctor",
      text: question,
      timestamp: format(new Date(), "HH:mm:ss"),
    });
  };

  const updateMed = (i: number, field: keyof Medication, value: string) => {
    const updated = [...prescription];
    updated[i] = { ...updated[i], [field]: value };
    setPrescription(updated);
  };

  const removeMed = (i: number) => setPrescription(prescription.filter((_, idx) => idx !== i));
  const addMed = () => setPrescription([...prescription, { name: "", dosage: "", frequency: "", duration: "" }]);

  const age = patient?.dateOfBirth
    ? Math.floor(
        (Date.now() - new Date(patient.dateOfBirth).getTime()) /
          (365.25 * 24 * 60 * 60 * 1000)
      )
    : null;

  if (detailLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-3">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Loading appointment...</p>
      </div>
    );
  }

  if (!appointment || !patient) {
    return (
      <div className="space-y-4 py-12 text-center">
        <p className="text-sm text-muted-foreground">
          {detailError || "Appointment not found."}
        </p>
        <Button variant="outline" onClick={() => navigate("/agenda")}>
          Back
        </Button>
      </div>
    );
  }

  // ─── BEFORE CONSULTATION ───
  if (!consultationStarted) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>

        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-foreground">{appointment.patientName}</h1>
            <p className="text-sm text-muted-foreground">
              {appointment.motif} · {appointment.time}
            </p>
          </div>
          <Button
            onClick={startConsultation}
            className="gap-2 h-11 px-6 text-sm font-semibold shadow-[0_4px_14px_rgba(0,112,201,0.25)] hover:shadow-[0_6px_20px_rgba(0,112,201,0.35)]"
          >
            <Play className="h-4 w-4" />
            Start Appointment
          </Button>
        </div>

        {/* AI Briefing */}
        {appointment.aiSummary && (
          <div className="rounded-lg bg-card border border-border border-l-[3px] border-l-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)] p-5 space-y-3">
            <h2 className="text-sm font-medium text-foreground flex items-center gap-2">
              <Stethoscope className="h-4 w-4 text-primary" />
              AI Phone Briefing
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">{appointment.aiSummary}</p>
            {relatedCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {relatedCalls[0].symptoms.map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium bg-secondary text-primary"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Patient info */}
        <div className="rounded-lg bg-card border border-border shadow-[0_1px_3px_rgba(0,0,0,0.08)] p-5 space-y-4">
          <h2 className="text-sm font-medium text-foreground">Patient Profile</h2>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-md bg-muted px-3 py-2.5">
              <p className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">Age</p>
              <p className="text-foreground font-medium">{age !== null ? `${age} years` : "Unknown"}</p>
            </div>
            <div className="rounded-md bg-muted px-3 py-2.5">
              <p className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">Blood type</p>
              <p className="text-foreground font-medium">{patient.bloodType}</p>
            </div>
            <div className="rounded-md bg-muted px-3 py-2.5">
              <p className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">Allergies</p>
              <div className="flex gap-1 flex-wrap mt-0.5">
                {patient.allergies.length > 0
                  ? patient.allergies.map((a) => (
                      <span
                        key={a}
                        className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium bg-[#FEE2E2] text-destructive"
                      >
                        {a}
                      </span>
                    ))
                  : <span className="text-foreground text-sm">None</span>}
              </div>
            </div>
          </div>
          {patient.antecedents.length > 0 && (
            <>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-2">Medical history</p>
                <ul className="space-y-1">
                  {patient.antecedents.map((a, i) => (
                    <li key={i} className="text-sm text-muted-foreground">
                      • {a}
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>

        {/* History timeline */}
        {history.length > 0 && (
          <div className="rounded-lg bg-card border border-border shadow-[0_1px_3px_rgba(0,0,0,0.08)] p-5 space-y-4">
            <h2 className="text-sm font-medium text-foreground">History</h2>
            <div className="relative">
              {history.map((h, i) => (
                <div key={i} className="flex gap-4 text-sm relative">
                  <div className="text-xs text-muted-foreground font-mono w-20 shrink-0 pt-1">
                    {format(new Date(h.date), "dd MMM yy", { locale: enUS })}
                  </div>
                  <div className="flex flex-col items-center shrink-0">
                    <div className="h-2.5 w-2.5 rounded-full bg-primary/40 border-2 border-primary/20 mt-1.5 z-10" />
                    {i < history.length - 1 && <div className="w-px flex-1 bg-border" />}
                  </div>
                  <div className="flex-1 pb-5">
                    <p className="font-medium text-foreground text-sm">{h.motif}</p>
                    <p className="text-muted-foreground text-xs mt-1">{h.summary}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ─── DURING CONSULTATION (split panel) ───
  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-card shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/")} className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <span className="text-sm font-medium text-foreground">{appointment.patientName}</span>
            <span className="text-xs text-muted-foreground ml-2">{appointment.motif}</span>
          </div>
          {!consultationEnded && (
            <>
              <div className="flex items-center gap-1.5 ml-2">
                <span className="h-2 w-2 rounded-full bg-destructive animate-pulse" />
                <span className="text-xs text-muted-foreground">In progress</span>
              </div>
              {wsConnected && (
                <div className="flex items-center gap-1.5 ml-3 px-2 py-0.5 rounded-full bg-destructive/10">
                  <Radio className="h-3 w-3 text-destructive animate-pulse" />
                  <span className="text-[11px] text-destructive font-medium">Recording active</span>
                </div>
              )}
            </>
          )}
        </div>
        {!consultationEnded && (
          <Button
            onClick={endConsultation}
            variant="outline"
            size="sm"
            className="gap-2 border-destructive/40 text-destructive hover:bg-destructive/5"
          >
            <Square className="h-3 w-3" />
            End Appointment
          </Button>
        )}
      </div>

      {consultationEnded && !summaryLoading && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="p-4 bg-success/10 border-b border-success/20 text-center"
        >
          <p className="text-sm text-success font-medium">Consultation completed</p>
        </motion.div>
      )}

      {/* Split panel */}
      {token && liveKitUrl ? (
        <LiveKitRoom
          video={false}
          audio={true}
          token={token}
          serverUrl={liveKitUrl}
          connect={consultationStarted && (!consultationEnded || endingRequested)}
          className="flex-1 flex overflow-hidden"
        >
          <RoomAudioRenderer />
          <LiveKitTranscriptListener onTranscript={injectMessage} 
             shouldRequestEnd={endingRequested}
             consultationContext={consultationContext}
             onSuggestions={(questions, flags) => {
               applySuggestionUpdate(questions, flags);
             }}
             onSoap={(soapData) => { void handleSoap(soapData); }}
          />
          {/* LEFT: Conversation */}
          <div className="flex-1 flex flex-col border-r border-border bg-background">
            <div className="px-4 py-3 border-b border-border shrink-0 flex items-center gap-2 bg-card">
              <span className="h-2 w-2 rounded-full bg-primary" />
              <span className="text-xs font-medium text-foreground">Conversation Transcript</span>
              <span className="text-[10px] text-muted-foreground ml-auto">{transcript.length} msg</span>
            </div>
            <ScrollArea className="flex-1 p-4">
              <div className="space-y-2">
                {transcript.length === 0 ? (
                  <div className="h-full flex items-center justify-center">
                    <div className="text-center max-w-sm space-y-2">
                      <p className="text-sm font-medium text-foreground">
                        {consultationEnded ? "No transcript available." : "Waiting for transcript..."}
                      </p>
                      {!consultationEnded && (
                        <p className="text-xs text-muted-foreground">
                          Speak to start streaming the conversation.
                        </p>
                      )}
                    </div>
                  </div>
                ) : (
                  transcript.map((msg, i) => (
                    <div
                      key={`conv-${i}`}
                      className={`px-3 py-2 rounded-md text-xs ${
                        msg.speaker === "Doctor" ? "bg-[#EEF6FF]" : "bg-[#F8FAFC]"
                      }`}
                    >
                      <span
                        className={`font-semibold mr-1.5 ${
                          msg.speaker === "Doctor" ? "text-primary" : "text-foreground"
                        }`}
                      >
                        {msg.speaker === "Doctor" ? "Dr." : "Patient"}
                      </span>
                      <span className="text-foreground/90">{msg.text}</span>
                      <span className="text-[10px] text-muted-foreground ml-1.5">
                        {msg.timestamp}
                      </span>
                    </div>
                  ))
                )}
                <div ref={transcriptEndRef} />
              </div>
            </ScrollArea>
            {!consultationEnded && (
              <div className="p-3 border-t border-border bg-card shrink-0 flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  Live transcript is streaming in real time.
                </p>
                <TrackToggle
                  source={Track.Source.Microphone}
                  className="inline-flex items-center justify-center whitespace-nowrap text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 h-9 rounded-md px-3 bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
                >
                  Toggle Mic
                </TrackToggle>
              </div>
            )}
          </div>

          {/* RIGHT: AI Summary + Prescription */}
          <div className="w-[420px] flex flex-col shrink-0 bg-card">
            {/* Suggested questions */}
            {!consultationEnded && (
              <div className="max-h-[32%] flex flex-col border-b border-border overflow-hidden">
                <div className="px-4 py-3 border-b border-border shrink-0 flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-primary" />
                  <span className="text-xs font-medium text-foreground">Suggested questions</span>
                </div>
                <ScrollArea className="flex-1 p-4">
                  {redFlags.length > 0 && (
                    <div className="mb-3 p-2.5 rounded-lg bg-[#FEE2E2] border border-destructive/20">
                      <p className="text-[11px] font-semibold text-destructive mb-1">Red flags</p>
                      {redFlags.map((flag) => (
                        <p key={flag} className="text-[11px] text-destructive">{flag}</p>
                      ))}
                    </div>
                  )}
                  <div className="space-y-2">
                    {(suggestedQuestions.length > 0
                      ? suggestedQuestions
                      : ["Suggested questions will appear here in real time."]
                    ).map((question) => (
                      <button
                        key={question}
                        disabled={suggestedQuestions.length === 0}
                        onClick={() => applySuggestedQuestion(question)}
                        className="w-full text-left rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground hover:border-primary/40 disabled:opacity-70"
                      >
                        {question}
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}

            {/* AI Summary */}
            <div className="flex-1 flex flex-col border-b border-border overflow-hidden">
              <div className="px-4 py-3 border-b border-border shrink-0 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-accent-foreground" />
                <span className="text-xs font-medium text-foreground">AI Summary</span>
              </div>
              <ScrollArea className="flex-1 p-4">
                {summaryLoading ? (
                  <div className="flex flex-col items-center justify-center py-16 space-y-3">
                    <Loader2 className="h-6 w-6 text-primary animate-spin" />
                    <p className="text-sm text-muted-foreground">Analyzing consultation...</p>
                  </div>
                ) : aiSummary ? (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                    <p className="text-sm text-foreground/90 leading-relaxed">{aiSummary}</p>
                    {detectedSymptoms.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-2">Detected symptoms</p>
                        <div className="flex flex-wrap gap-1">
                          {detectedSymptoms.map((s) => (
                            <span
                              key={s}
                              className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-medium bg-secondary text-primary"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {diagnoses.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Diagnostic probable</p>
                        <ul className="space-y-1">
                          {diagnoses.map((d, i) => (
                            <li key={i} className="text-xs text-foreground/80 flex items-center gap-2">
                              <span
                                className={`h-1.5 w-1.5 rounded-full ${
                                  i === 0 ? "bg-primary" : "bg-muted-foreground/30"
                                }`}
                              />
                              {d}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {contextSignals.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Patient context used</p>
                        <ul className="space-y-1">
                          {contextSignals.map((signal, i) => (
                            <li key={i} className="text-xs text-foreground/80">
                              • {signal}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {soapPayload?.followups?.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Follow-up points</p>
                        <ul className="space-y-1">
                          {soapPayload.followups.slice(0, 4).map((point: string, i: number) => (
                            <li key={i} className="text-xs text-foreground/80">
                              • {point}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </motion.div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-10">
                    {consultationEnded
                      ? "No summary available."
                      : "The summary will be generated at the end of the consultation..."}
                  </p>
                )}
              </ScrollArea>
            </div>

            {/* Prescription */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-4 py-3 border-b border-border shrink-0 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-warning" />
                  <span className="text-xs font-medium text-foreground">Prescription</span>
                </div>
                {validated && (
                    <Badge className="bg-success/10 text-success border-success/20 text-[10px]">
                    Validated
                  </Badge>
                )}
              </div>
              <ScrollArea className="flex-1 p-4">
                {summaryLoading ? (
                  <div className="flex flex-col items-center justify-center py-10 space-y-3">
                    <Loader2 className="h-5 w-5 text-muted-foreground animate-spin" />
                    <p className="text-xs text-muted-foreground">Generating prescription...</p>
                  </div>
                ) : !showPrescription ? (
                  <p className="text-sm text-muted-foreground text-center py-10">
                    {consultationEnded
                      ? "No prescription generated."
                      : "The prescription will be generated at the end of the consultation..."}
                  </p>
                ) : (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="space-y-3"
                  >
                    {hasAllergyConflict && !validated && (
                      <div className="p-2.5 rounded-lg bg-[#FEE2E2] border border-destructive/20 flex items-start gap-2">
                        <AlertTriangle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                        <p className="text-xs text-destructive">
                          Penicillin allergy detected - Amoxicillin is incompatible
                        </p>
                      </div>
                    )}

                    {prescription.map((med, i) => (
                      <div key={i} className="p-4 rounded-lg bg-background border border-border space-y-3">
                        {!validated ? (
                          <>
                            <div className="flex items-center justify-between">
                              <div className="flex-1">
                                <label className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 block">
                                  Medication
                                </label>
                                <Input
                                  value={med.name}
                                  onChange={(e) => updateMed(i, "name", e.target.value)}
                                  className="h-8 text-sm bg-card border-input font-medium focus-visible:ring-primary"
                                  placeholder="Medication"
                                />
                              </div>
                              <button
                                onClick={() => removeMed(i)}
                                className="text-muted-foreground hover:text-destructive ml-2 mt-4"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                              <div>
                                <label className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 block">
                                  Dosage
                                </label>
                                <Input
                                  value={med.dosage}
                                  onChange={(e) => updateMed(i, "dosage", e.target.value)}
                                  className="h-8 text-xs bg-card border-input focus-visible:ring-primary"
                                  placeholder="Dosage"
                                />
                              </div>
                              <div>
                                <label className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 block">
                                  Frequency
                                </label>
                                <Input
                                  value={med.frequency}
                                  onChange={(e) => updateMed(i, "frequency", e.target.value)}
                                  className="h-8 text-xs bg-card border-input focus-visible:ring-primary"
                                  placeholder="Frequency"
                                />
                              </div>
                              <div>
                                <label className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 block">
                                  Duration
                                </label>
                                <Input
                                  value={med.duration}
                                  onChange={(e) => updateMed(i, "duration", e.target.value)}
                                  className="h-8 text-xs bg-card border-input focus-visible:ring-primary"
                                  placeholder="Duration"
                                />
                              </div>
                            </div>
                          </>
                        ) : (
                          <>
                            <p className="text-sm font-medium text-foreground">
                              {med.name} — {med.dosage}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {med.frequency} · {med.duration}
                            </p>
                          </>
                        )}
                      </div>
                    ))}

                    {!validated && (
                      <button
                        onClick={addMed}
                        className="w-full py-2.5 rounded-lg border border-dashed border-border text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 transition-colors flex items-center justify-center gap-1"
                      >
                        <Plus className="h-3 w-3" /> Add medication
                      </button>
                    )}
                  </motion.div>
                )}
              </ScrollArea>
              {showPrescription && (
                <div className="p-4 border-t border-border shrink-0">
                  <Button onClick={handleValidateAndSend} className="w-full gap-2" size="default" disabled={sendingPrescription}>
                    {sendingPrescription ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    {sendingPrescription ? "Sending..." : validated ? "Send Again (Test)" : "Validate & Send"}
                  </Button>
                </div>
              )}
              {consultationEnded && (
                <div className="p-4 border-t border-border shrink-0">
                  <Button
                    onClick={launchReminderCall}
                    disabled={isLaunchingReminder}
                    variant="outline"
                    className="w-full gap-2"
                  >
                    {isLaunchingReminder ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Launching...
                      </>
                    ) : (
                      <>
                        <PhoneCall className="h-4 w-4" />
                        Trigger Follow-up Call
                      </>
                    )}
                  </Button>
                </div>
              )}
            </div>
          </div>
        </LiveKitRoom>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          {consultationStarted ? (
            <div className="flex flex-col items-center space-y-3">
              <Loader2 className="h-6 w-6 text-primary animate-spin" />
              <p className="text-sm text-muted-foreground">Connecting to Voice Agent...</p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Click start to begin the consultation.</p>
          )}
        </div>
      )}
    </div>
  );
}
