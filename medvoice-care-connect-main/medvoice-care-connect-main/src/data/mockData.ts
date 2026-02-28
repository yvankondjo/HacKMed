import { format } from "date-fns";

const today = format(new Date(), "yyyy-MM-dd");

export interface Patient {
  id: string;
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  phone: string;
  email: string;
  bloodType: string;
  allergies: string[];
  antecedents: string[];
}

export interface Appointment {
  id: string;
  patientId: string;
  patientName: string;
  date: string;
  time: string;
  doctor: string;
  doctorSpecialty: string;
  motif: string;
  status: "upcoming" | "in-progress" | "done";
  notes?: string;
  aiSummary?: string;
}

export interface CallRecord {
  id: string;
  patientId: string;
  appointmentId?: string;
  date: string;
  duration: string;
  motif: string;
  symptoms: string[];
  summary: string;
  recommendations: string[];
  evolution: "improvement" | "worsening" | "stable";
  urgencyScore: number;
}

export interface Notification {
  id: string;
  type: "reminder" | "document" | "alert";
  message: string;
  date: string;
  read: boolean;
}

export interface Medication {
  name: string;
  dosage: string;
  frequency: string;
  duration: string;
}

export interface Prescription {
  medications: Medication[];
  additionalAdvice: string[];
}

export interface TranscriptMessage {
  role: "doctor" | "patient";
  text: string;
  timestamp?: string;
}

export interface PastAppointment {
  date: string;
  motif: string;
  doctor: string;
  summary: string;
}

// ─── Patients ───

export const patients: Patient[] = [
  {
    id: "1",
    firstName: "Marie",
    lastName: "Dupont",
    dateOfBirth: "1978-06-15",
    phone: "06 12 34 56 78",
    email: "marie.dupont@email.com",
    bloodType: "A+",
    allergies: ["Pénicilline", "Arachides"],
    antecedents: [
      "Hypertension artérielle (depuis 2019)",
      "Appendicectomie (2005)",
      "Fracture poignet droit (2012)",
      "Antécédents familiaux : diabète type 2 (père)",
    ],
  },
  {
    id: "2",
    firstName: "Jean",
    lastName: "Martin",
    dateOfBirth: "1985-03-22",
    phone: "06 98 76 54 32",
    email: "jean.martin@email.com",
    bloodType: "O-",
    allergies: ["Aspirine"],
    antecedents: ["Asthme chronique (depuis 2010)", "Entorse cheville gauche (2018)"],
  },
  {
    id: "3",
    firstName: "Sophie",
    lastName: "Bernard",
    dateOfBirth: "1992-11-08",
    phone: "06 55 44 33 22",
    email: "sophie.bernard@email.com",
    bloodType: "B+",
    allergies: [],
    antecedents: ["Migraine chronique (depuis 2020)"],
  },
];

export const patient = patients[0]; // backward compat

// ─── Today's Appointments ───

export const appointments: Appointment[] = [
  {
    id: "1",
    patientId: "1",
    patientName: "Marie Dupont",
    date: today,
    time: "09:00",
    doctor: "Dr. Laurent Martin",
    doctorSpecialty: "Médecin généraliste",
    motif: "Suivi tensions artérielles",
    status: "done",
    aiSummary:
      "La patiente a appelé pour un suivi de sa tension artérielle. Elle mentionne des vertiges matinaux depuis 1 semaine. L'agent a recommandé de maintenir le traitement actuel et de venir avec ses relevés tensionnels des 2 dernières semaines.",
  },
  {
    id: "2",
    patientId: "2",
    patientName: "Jean Martin",
    date: today,
    time: "10:30",
    doctor: "Dr. Laurent Martin",
    doctorSpecialty: "Médecin généraliste",
    motif: "Crise d'asthme récurrente",
    status: "upcoming",
    aiSummary:
      "Le patient signale une augmentation de la fréquence des crises d'asthme, surtout la nuit. Il utilise son inhalateur de secours 3-4 fois par semaine au lieu d'une fois. Pas de modification récente de l'environnement.",
  },
  {
    id: "3",
    patientId: "3",
    patientName: "Sophie Bernard",
    date: today,
    time: "11:30",
    doctor: "Dr. Laurent Martin",
    doctorSpecialty: "Médecin généraliste",
    motif: "Migraines persistantes",
    status: "upcoming",
    aiSummary:
      "La patiente souffre de migraines 4 à 5 fois par semaine depuis un mois, avec photophobie et nausées. Le traitement actuel (paracétamol) ne suffit plus. Elle demande un ajustement thérapeutique.",
  },
  {
    id: "4",
    patientId: "1",
    patientName: "Marie Dupont",
    date: today,
    time: "14:00",
    doctor: "Dr. Laurent Martin",
    doctorSpecialty: "Médecin généraliste",
    motif: "Toux persistante",
    status: "upcoming",
    aiSummary:
      "La patiente tousse depuis 3 semaines. Toux sèche, non productive, sans fièvre. Pas de tabagisme. L'agent a recommandé une consultation pour investigation complémentaire.",
  },
  {
    id: "5",
    patientId: "2",
    patientName: "Jean Martin",
    date: today,
    time: "15:30",
    doctor: "Dr. Laurent Martin",
    doctorSpecialty: "Médecin généraliste",
    motif: "Douleurs lombaires",
    status: "upcoming",
    aiSummary:
      "Le patient décrit des douleurs lombaires basses depuis 2 semaines, irradiant dans la jambe droite. Apparition après un effort de levage. Pas de perte de sensibilité.",
  },
];

// ─── Past appointments per patient ───

export const pastAppointments: Record<string, PastAppointment[]> = {
  "1": [
    { date: "2026-02-15", motif: "Renouvellement ordonnance", doctor: "Dr. Martin", summary: "Renouvellement traitement hypertension. Résultats satisfaisants." },
    { date: "2026-01-20", motif: "Douleurs thoraciques", doctor: "Dr. Martin", summary: "Bilan cardiaque normal. Stress identifié comme cause probable." },
    { date: "2025-11-10", motif: "Bilan annuel", doctor: "Dr. Martin", summary: "Bilan sanguin complet. Cholestérol légèrement élevé." },
  ],
  "2": [
    { date: "2026-02-01", motif: "Crise d'asthme", doctor: "Dr. Martin", summary: "Crise modérée. Ajustement posologie Ventoline." },
    { date: "2025-12-15", motif: "Bilan respiratoire", doctor: "Dr. Martin", summary: "EFR satisfaisantes. Maintien traitement de fond." },
  ],
  "3": [
    { date: "2026-01-28", motif: "Migraines", doctor: "Dr. Martin", summary: "Prescription Sumatriptan. Tenu journal des crises." },
  ],
};

// ─── Call records ───

export const calls: CallRecord[] = [
  {
    id: "1",
    patientId: "1",
    appointmentId: "1",
    date: "2026-02-27",
    duration: "8 min",
    motif: "Prise de RDV — Suivi tensions",
    symptoms: ["Vertiges matinaux", "Céphalées"],
    summary: "La patiente a contacté l'assistant pour planifier un suivi de ses tensions artérielles.",
    recommendations: ["Mesurer la tension matin et soir", "Apporter les relevés au RDV"],
    evolution: "stable",
    urgencyScore: 4,
  },
  {
    id: "2",
    patientId: "2",
    appointmentId: "2",
    date: "2026-02-26",
    duration: "6 min",
    motif: "Prise de RDV — Asthme",
    symptoms: ["Dyspnée nocturne", "Sifflements"],
    summary: "Le patient signale une augmentation des crises d'asthme nocturnes.",
    recommendations: ["Éviter les allergènes", "Utiliser le peak flow quotidiennement"],
    evolution: "worsening",
    urgencyScore: 5,
  },
];

// ─── Mock transcript for consultation simulation ───

export const mockTranscriptSteps: TranscriptMessage[] = [
  { role: "patient", text: "Bonjour docteur, j'ai mal à la gorge depuis 3 jours.", timestamp: "00:00" },
  { role: "doctor", text: "Bonjour. Pouvez-vous me décrire la douleur ? Est-ce constant ?", timestamp: "00:12" },
  { role: "patient", text: "Oui, c'est constant et ça empire quand j'avale.", timestamp: "00:25" },
  { role: "doctor", text: "Avez-vous de la fièvre ?", timestamp: "00:35" },
  { role: "patient", text: "Oui, autour de 38.5°C hier soir.", timestamp: "00:42" },
  { role: "doctor", text: "Des ganglions gonflés au niveau du cou ?", timestamp: "00:55" },
  { role: "patient", text: "Je crois que oui, c'est sensible quand j'appuie.", timestamp: "01:05" },
  { role: "doctor", text: "Depuis combien de temps exactement ?", timestamp: "01:18" },
  { role: "patient", text: "Ça a commencé lundi, donc 3 jours.", timestamp: "01:28" },
  { role: "doctor", text: "D'accord. Je vais vous examiner. Ouvrez la bouche.", timestamp: "01:40" },
];

export const mockAIPrescription: Prescription = {
  medications: [
    { name: "Amoxicilline", dosage: "1g", frequency: "3 fois par jour", duration: "6 jours" },
    { name: "Paracétamol", dosage: "1000mg", frequency: "Toutes les 6h si douleur", duration: "5 jours" },
    { name: "Hexaspray", dosage: "2 pulvérisations", frequency: "3 fois par jour", duration: "5 jours" },
  ],
  additionalAdvice: [
    "Repos vocal recommandé",
    "Hydratation abondante (1.5L/jour minimum)",
    "Éviter les aliments irritants",
    "Reconsulter si fièvre persiste au-delà de 48h",
  ],
};

export const mockDiagnoses = [
  "Angine bactérienne (streptocoque probable)",
  "Pharyngite aiguë",
  "Infection virale des VAS",
];

export const notifications: Notification[] = [
  { id: "1", type: "reminder", message: "RDV avec Marie Dupont dans 30 min", date: today, read: false },
  { id: "2", type: "alert", message: "Résultat labo Jean Martin disponible", date: today, read: false },
  { id: "3", type: "document", message: "Ordonnance à signer", date: today, read: true },
];

export interface LifecycleTableImpact {
  table: string;
  eventLabel: string;
}

export interface LifecycleStage {
  id: string;
  title: string;
  description: string;
  status: "done" | "active" | "next";
  impactedTables: LifecycleTableImpact[];
}

export const productLifecycleStages: LifecycleStage[] = [
  {
    id: "patient-call",
    title: "Patient appelle",
    description: "Capture du besoin, qualification initiale et creation de rendez-vous.",
    status: "done",
    impactedTables: [
      { table: "users", eventLabel: "lookup/create patient user" },
      { table: "patients", eventLabel: "lookup/create patient profile" },
      { table: "appointments", eventLabel: "create appointment status=upcoming" },
      { table: "ai_summaries", eventLabel: "insert type=phone_briefing" },
      { table: "call_records", eventLabel: "insert inbound intake call" },
      { table: "sms_messages", eventLabel: "insert type=booking_confirmation" },
    ],
  },
  {
    id: "day-before-confirmation",
    title: "Confirmation J-1",
    description: "Relance patient et validation de presence avant consultation.",
    status: "done",
    impactedTables: [
      { table: "sms_messages", eventLabel: "insert type=reminder" },
      { table: "call_records", eventLabel: "optional confirmation call" },
      { table: "appointments", eventLabel: "update status=confirmed" },
    ],
  },
  {
    id: "consultation-start",
    title: "Consultation demarre",
    description: "Debut de session clinique avec transcription live et resume progressif.",
    status: "active",
    impactedTables: [
      { table: "consultations", eventLabel: "insert state=active, started_at" },
      { table: "transcript_messages", eventLabel: "stream doctor/patient/ai utterances" },
      { table: "ai_summaries", eventLabel: "insert type=live_summary" },
    ],
  },
  {
    id: "consultation-end-prescription",
    title: "Fin consultation + ordonnance",
    description: "Cloture medicale, generation du compte-rendu et envoi ordonnance.",
    status: "next",
    impactedTables: [
      { table: "ai_summaries", eventLabel: "insert type=final_report" },
      { table: "prescriptions", eventLabel: "insert/validate prescription" },
      { table: "prescription_items", eventLabel: "insert medication lines" },
      { table: "sms_messages", eventLabel: "insert type=prescription" },
    ],
  },
  {
    id: "post-consultation-followup",
    title: "Suivi post-consultation",
    description: "Automatisation des rappels et monitorage d'evolution.",
    status: "next",
    impactedTables: [
      { table: "followup_tasks", eventLabel: "insert follow-up workflow tasks" },
      { table: "sms_messages", eventLabel: "insert type=followup" },
      { table: "call_records", eventLabel: "insert outbound follow-up call" },
    ],
  },
];
