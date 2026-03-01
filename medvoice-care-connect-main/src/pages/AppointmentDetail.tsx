import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  Play,
  Square,
  Plus,
  Trash2,
  AlertTriangle,
  Send,
  Mic,
  Stethoscope,
  Loader2,
  Radio,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  mockTranscriptSteps,
  type Medication,
} from "@/data/mockData";
import { useTranscriptSocket, type TranscriptEntry } from "@/hooks/useTranscriptSocket";
import { fetchConsultationSummary, fetchSuggestedQuestions } from "@/services/consultationApi";
import {
  fetchAppointmentDetail,
  type DashboardAppointmentDetail,
} from "@/services/careDataApi";
import { postConsultationEnd, postConsultationStart, postTranscriptBatch } from "@/services/lifecycleApi";

export default function AppointmentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const lastSyncedTranscriptRef = useRef(0);
  const [detail, setDetail] = useState<DashboardAppointmentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);

  // ─── Consultation state ───
  const [consultationStarted, setConsultationStarted] = useState(false);
  const [consultationEnded, setConsultationEnded] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);

  // ─── AI / Prescription state ───
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [detectedSymptoms, setDetectedSymptoms] = useState<string[]>([]);
  const [diagnoses, setDiagnoses] = useState<string[]>([]);
  const [prescription, setPrescription] = useState<Medication[]>([]);
  const [showPrescription, setShowPrescription] = useState(false);
  const [validated, setValidated] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [redFlags, setRedFlags] = useState<string[]>([]);

  // ─── WebSocket transcript ───
  const {
    connected: wsConnected,
    transcript,
    connect: wsConnect,
    disconnect: wsDisconnect,
    injectMessage,
    getSerializableTranscript,
  } = useTranscriptSocket({
    // Pass a real WS URL here when Speechmatics is integrated
    url: null,
  });

  useEffect(() => {
    let active = true;
    const run = async () => {
      if (!id) {
        if (active) {
          setDetail(null);
          setLoadingDetail(false);
        }
        return;
      }
      try {
        const payload = await fetchAppointmentDetail(id);
        if (active) setDetail(payload);
      } finally {
        if (active) setLoadingDetail(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [id]);

  const appointment = detail?.appointment;
  const patient = detail?.patient;
  const history = detail?.history || [];
  const relatedCalls = detail?.calls || [];
  const appointmentId = appointment?.id;
  const patientId = patient?.id;

  const hasAllergyConflict =
    patient?.allergies.some((a) => a.toLowerCase().includes("pénicilline")) &&
    prescription.some((m) => m.name.toLowerCase().includes("amoxicilline"));

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  useEffect(() => {
    if (!appointmentId || !patientId) return;
    if (!consultationStarted || consultationEnded) return;
    if (transcript.length <= lastSyncedTranscriptRef.current) return;
    const unsynced = transcript.slice(lastSyncedTranscriptRef.current);
    lastSyncedTranscriptRef.current = transcript.length;

    void postTranscriptBatch(appointmentId, patientId, unsynced);
  }, [consultationStarted, consultationEnded, transcript, appointmentId, patientId]);

  useEffect(() => {
    if (!appointmentId || !patientId) return;
    if (!consultationStarted || consultationEnded || transcript.length === 0) return;
    const timer = setTimeout(async () => {
      try {
        const result = await fetchSuggestedQuestions({
          appointmentId,
          patientId,
          transcript: getSerializableTranscript(),
        });
        setSuggestedQuestions(result.questions);
        setRedFlags(result.redFlags);
      } catch {
        // keep last suggestions on transient errors
      }
    }, 400);

    return () => clearTimeout(timer);
  }, [
    consultationStarted,
    consultationEnded,
    transcript,
    appointmentId,
    patientId,
    getSerializableTranscript,
  ]);

  if (loadingDetail) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-4">
        <Loader2 className="h-5 w-5 text-primary animate-spin" />
        <p className="text-muted-foreground text-sm">Chargement du rendez-vous...</p>
      </div>
    );
  }

  if (!appointment || !patient) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-4">
        <p className="text-muted-foreground text-sm">Rendez-vous introuvable.</p>
        <Button variant="outline" size="sm" onClick={() => navigate("/")}>
          Retour
        </Button>
      </div>
    );
  }

  // ─── Demo: simulate WebSocket messages ───
  const simulateNextLines = () => {
    if (stepIndex >= mockTranscriptSteps.length) return;
    let idx = stepIndex;

    const inject = (mock: (typeof mockTranscriptSteps)[0]) => {
      const entry: TranscriptEntry = {
        speaker: mock.role === "doctor" ? "Doctor" : "Patient",
        text: mock.text,
        timestamp: mock.timestamp || format(new Date(), "HH:mm:ss"),
      };
      injectMessage(entry);
    };

    if (idx < mockTranscriptSteps.length) { inject(mockTranscriptSteps[idx]); idx++; }
    if (idx < mockTranscriptSteps.length) { inject(mockTranscriptSteps[idx]); idx++; }
    setStepIndex(idx);
  };

  const startConsultation = () => {
    if (!appointmentId || !patientId) return;
    setConsultationStarted(true);
    lastSyncedTranscriptRef.current = 0;
    wsConnect();
    void postConsultationStart(appointmentId, patientId);
  };

  const endConsultation = async () => {
    if (!appointmentId || !patientId) return;
    wsDisconnect();
    setConsultationEnded(true);
    setSummaryLoading(true);

    try {
      await postConsultationEnd(appointmentId);
      const serializableTranscript = getSerializableTranscript();
      const result = await fetchConsultationSummary({
        appointmentId,
        patientId,
        transcript: serializableTranscript,
      });

      setAiSummary(result.summary);
      setDetectedSymptoms(result.detectedSymptoms);
      setDiagnoses(result.diagnoses);
      setPrescription(result.prescription.medications);
      setShowPrescription(true);
    } catch (err) {
      console.error("Failed to fetch consultation summary:", err);
      setAiSummary("Erreur lors de la génération du résumé. Veuillez réessayer.");
    } finally {
      setSummaryLoading(false);
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

  const birthTs = new Date(patient.dateOfBirth).getTime();
  const age = Number.isFinite(birthTs)
    ? Math.floor((Date.now() - birthTs) / (365.25 * 24 * 60 * 60 * 1000))
    : null;

  // ─── BEFORE CONSULTATION ───
  if (!consultationStarted) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Retour
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
              <p className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">Âge</p>
              <p className="text-foreground font-medium">{age !== null ? `${age} ans` : "Inconnu"}</p>
            </div>
            <div className="rounded-md bg-muted px-3 py-2.5">
              <p className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">Groupe sanguin</p>
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
                  : <span className="text-foreground text-sm">Aucune</span>}
              </div>
            </div>
          </div>
          {patient.antecedents.length > 0 && (
            <>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-2">Antécédents</p>
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
            <h2 className="text-sm font-medium text-foreground">Historique</h2>
            <div className="relative">
              {history.map((h, i) => (
                <div key={i} className="flex gap-4 text-sm relative">
                  <div className="text-xs text-muted-foreground font-mono w-20 shrink-0 pt-1">
                    {format(new Date(h.date), "dd MMM yy", { locale: fr })}
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
                <span className="text-xs text-muted-foreground">En cours</span>
              </div>
              {wsConnected && (
                <div className="flex items-center gap-1.5 ml-3 px-2 py-0.5 rounded-full bg-destructive/10">
                  <Radio className="h-3 w-3 text-destructive animate-pulse" />
                  <span className="text-[11px] text-destructive font-medium">Enregistrement actif</span>
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
          <p className="text-sm text-success font-medium">Consultation terminée</p>
        </motion.div>
      )}

      {/* Split panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT: Live Transcript */}
        <div className="flex-1 flex flex-col border-r border-border bg-background">
          <div className="px-4 py-3 border-b border-border shrink-0 flex items-center gap-2 bg-card">
            <span className="h-2 w-2 rounded-full bg-primary" />
            <span className="text-xs font-medium text-foreground">Live Transcript</span>
            <span className="text-[10px] text-muted-foreground ml-auto">
              {transcript.length} message{transcript.length !== 1 ? "s" : ""}
            </span>
          </div>
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-2">
              <AnimatePresence>
                {transcript.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2 }}
                    className={`px-4 py-3 rounded-lg text-sm ${
                      msg.speaker === "Doctor" ? "bg-[#EEF6FF]" : "bg-[#F8FAFC]"
                    }`}
                  >
                    <span
                      className={`font-semibold text-xs mr-2 ${
                        msg.speaker === "Doctor" ? "text-primary" : "text-foreground"
                      }`}
                    >
                      {msg.speaker === "Doctor" ? "Dr." : "Patient"}
                    </span>
                    <span className="text-foreground/90">{msg.text}</span>
                    <span className="text-[10px] text-muted-foreground ml-2">{msg.timestamp}</span>
                  </motion.div>
                ))}
              </AnimatePresence>
              {transcript.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-16">
                  En attente de la conversation...
                </p>
              )}
              <div ref={transcriptEndRef} />
            </div>
          </ScrollArea>
          {!consultationEnded && (
            <div className="p-3 border-t border-border bg-card shrink-0">
              <Button
                onClick={simulateNextLines}
                disabled={stepIndex >= mockTranscriptSteps.length}
                variant="ghost"
                size="sm"
                className="gap-2 w-full text-muted-foreground"
              >
                <Mic className="h-3.5 w-3.5" />
                Simulate Speech (Demo)
              </Button>
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
                <span className="text-xs font-medium text-foreground">Questions proposées</span>
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
                    : ["La consultation va proposer des questions ici en live."]
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
                  <p className="text-sm text-muted-foreground">Analyse de la consultation...</p>
                </div>
              ) : aiSummary ? (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                  <p className="text-sm text-foreground/90 leading-relaxed">{aiSummary}</p>
                  {detectedSymptoms.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Symptômes détectés</p>
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
                </motion.div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-10">
                  {consultationEnded
                    ? "Aucun résumé disponible."
                    : "Le résumé sera généré à la fin de la consultation..."}
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
                  Validée
                </Badge>
              )}
            </div>
            <ScrollArea className="flex-1 p-4">
              {summaryLoading ? (
                <div className="flex flex-col items-center justify-center py-10 space-y-3">
                  <Loader2 className="h-5 w-5 text-muted-foreground animate-spin" />
                  <p className="text-xs text-muted-foreground">Génération de l'ordonnance...</p>
                </div>
              ) : !showPrescription ? (
                <p className="text-sm text-muted-foreground text-center py-10">
                  {consultationEnded
                    ? "Aucune ordonnance générée."
                    : "L'ordonnance sera générée à la fin de la consultation..."}
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
                        Allergie pénicilline détectée — Amoxicilline incompatible
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
                                Médicament
                              </label>
                              <Input
                                value={med.name}
                                onChange={(e) => updateMed(i, "name", e.target.value)}
                                className="h-8 text-sm bg-card border-input font-medium focus-visible:ring-primary"
                                placeholder="Médicament"
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
                                Fréquence
                              </label>
                              <Input
                                value={med.frequency}
                                onChange={(e) => updateMed(i, "frequency", e.target.value)}
                                className="h-8 text-xs bg-card border-input focus-visible:ring-primary"
                                placeholder="Fréquence"
                              />
                            </div>
                            <div>
                              <label className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 block">
                                Durée
                              </label>
                              <Input
                                value={med.duration}
                                onChange={(e) => updateMed(i, "duration", e.target.value)}
                                className="h-8 text-xs bg-card border-input focus-visible:ring-primary"
                                placeholder="Durée"
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
            {showPrescription && !validated && (
              <div className="p-4 border-t border-border shrink-0">
                <Button onClick={() => setValidated(true)} className="w-full gap-2" size="default">
                  <Send className="h-4 w-4" />
                  Validate & Send
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
