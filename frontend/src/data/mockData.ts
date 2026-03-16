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
    firstName: "Alice",
    lastName: "Example",
    dateOfBirth: "1978-06-15",
    phone: "06 00 00 00 01",
    email: "alice.example@example.test",
    bloodType: "A+",
    allergies: ["Penicillin", "Peanuts"],
    antecedents: [
      "Hypertension (since 2019)",
      "Appendectomy (2005)",
      "Right wrist fracture (2012)",
      "Family history: type 2 diabetes (father)",
    ],
  },
  {
    id: "2",
    firstName: "Bruno",
    lastName: "Sample",
    dateOfBirth: "1985-03-22",
    phone: "06 00 00 00 02",
    email: "bruno.sample@example.test",
    bloodType: "O-",
    allergies: ["Aspirin"],
    antecedents: ["Chronic asthma (since 2010)", "Left ankle sprain (2018)"],
  },
  {
    id: "3",
    firstName: "Chloe",
    lastName: "Demo",
    dateOfBirth: "1992-11-08",
    phone: "06 00 00 00 03",
    email: "chloe.demo@example.test",
    bloodType: "B+",
    allergies: [],
    antecedents: ["Chronic migraine (since 2020)"],
  },
];

export const patient = patients[0]; // backward compat

// ─── Today's Appointments ───

export const appointments: Appointment[] = [
  {
    id: "1",
    patientId: "1",
    patientName: "Alice Example",
    date: today,
    time: "09:00",
    doctor: "Dr. Alex Care",
    doctorSpecialty: "General practitioner",
    motif: "Blood pressure follow-up",
    status: "done",
    aiSummary:
      "The patient called for blood pressure follow-up. She reports morning dizziness for one week. The agent advised continuing current treatment and bringing blood pressure readings from the past two weeks.",
  },
  {
    id: "2",
    patientId: "2",
    patientName: "Bruno Sample",
    date: today,
    time: "10:30",
    doctor: "Dr. Alex Care",
    doctorSpecialty: "General practitioner",
    motif: "Recurrent asthma flare",
    status: "upcoming",
    aiSummary:
      "The patient reports more frequent asthma attacks, especially at night. Rescue inhaler use increased to 3-4 times weekly instead of once. No recent environmental changes.",
  },
  {
    id: "3",
    patientId: "3",
    patientName: "Chloe Demo",
    date: today,
    time: "11:30",
    doctor: "Dr. Alex Care",
    doctorSpecialty: "General practitioner",
    motif: "Persistent migraines",
    status: "upcoming",
    aiSummary:
      "The patient has migraines 4 to 5 times per week for one month, with photophobia and nausea. Current treatment (paracetamol) is no longer sufficient. She requests a treatment adjustment.",
  },
  {
    id: "4",
    patientId: "1",
    patientName: "Alice Example",
    date: today,
    time: "14:00",
    doctor: "Dr. Alex Care",
    doctorSpecialty: "General practitioner",
    motif: "Persistent cough",
    status: "upcoming",
    aiSummary:
      "The patient has had a dry, non-productive cough for three weeks without fever. No tobacco use. The agent recommended an in-person consultation for further evaluation.",
  },
  {
    id: "5",
    patientId: "2",
    patientName: "Bruno Sample",
    date: today,
    time: "15:30",
    doctor: "Dr. Alex Care",
    doctorSpecialty: "General practitioner",
    motif: "Low back pain",
    status: "upcoming",
    aiSummary:
      "The patient describes lower back pain for two weeks radiating to the right leg. Symptoms started after lifting effort. No sensory loss reported.",
  },
];

// ─── Past appointments per patient ───

export const pastAppointments: Record<string, PastAppointment[]> = {
  "1": [
    { date: "2026-02-15", motif: "Prescription renewal", doctor: "Dr. Care", summary: "Hypertension treatment renewed. Stable outcomes." },
    { date: "2026-01-20", motif: "Chest pain", doctor: "Dr. Care", summary: "Cardiac workup normal. Stress identified as likely cause." },
    { date: "2025-11-10", motif: "Annual checkup", doctor: "Dr. Care", summary: "Complete blood panel performed. Mildly elevated cholesterol." },
  ],
  "2": [
    { date: "2026-02-01", motif: "Asthma flare", doctor: "Dr. Care", summary: "Moderate flare. Ventoline dosage adjusted." },
    { date: "2025-12-15", motif: "Respiratory review", doctor: "Dr. Care", summary: "Pulmonary function tests stable. Maintenance therapy continued." },
  ],
  "3": [
    { date: "2026-01-28", motif: "Migraine review", doctor: "Dr. Care", summary: "Sumatriptan prescribed. Attack diary maintained." },
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
    motif: "Appointment booking - blood pressure follow-up",
    symptoms: ["Morning dizziness", "Headache"],
    summary: "The patient contacted the assistant to schedule blood pressure follow-up.",
    recommendations: ["Measure blood pressure morning and evening", "Bring readings to the appointment"],
    evolution: "stable",
    urgencyScore: 4,
  },
  {
    id: "2",
    patientId: "2",
    appointmentId: "2",
    date: "2026-02-26",
    duration: "6 min",
    motif: "Appointment booking - asthma",
    symptoms: ["Nocturnal dyspnea", "Wheezing"],
    summary: "The patient reports increased nocturnal asthma attacks.",
    recommendations: ["Avoid allergens", "Use peak flow daily"],
    evolution: "worsening",
    urgencyScore: 5,
  },
];

export const mockAIPrescription: Prescription = {
  medications: [
    { name: "Amoxicillin", dosage: "1g", frequency: "3 times daily", duration: "6 days" },
    { name: "Paracetamol", dosage: "1000mg", frequency: "Every 6h as needed for pain", duration: "5 days" },
    { name: "Hexaspray", dosage: "2 sprays", frequency: "3 times daily", duration: "5 days" },
  ],
  additionalAdvice: [
    "Voice rest is recommended",
    "Maintain good hydration (at least 1.5L/day)",
    "Avoid irritating foods",
    "Seek reassessment if fever persists beyond 48 hours",
  ],
};

export const notifications: Notification[] = [
  { id: "1", type: "reminder", message: "Appointment with Alice Example in 30 min", date: today, read: false },
  { id: "2", type: "alert", message: "Bruno Sample lab result available", date: today, read: false },
  { id: "3", type: "document", message: "Prescription ready for signature", date: today, read: true },
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
    title: "Patient Call",
    description: "Need capture, initial triage, and appointment creation.",
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
    title: "Day-Before Confirmation",
    description: "Patient reminder and attendance confirmation before consultation.",
    status: "done",
    impactedTables: [
      { table: "sms_messages", eventLabel: "insert type=reminder" },
      { table: "call_records", eventLabel: "optional confirmation call" },
      { table: "appointments", eventLabel: "update status=confirmed" },
    ],
  },
  {
    id: "consultation-start",
    title: "Consultation Started",
    description: "Clinical session started with live transcription and progressive summary.",
    status: "active",
    impactedTables: [
      { table: "consultations", eventLabel: "insert state=active, started_at" },
      { table: "transcript_messages", eventLabel: "stream doctor/patient/ai utterances" },
      { table: "ai_summaries", eventLabel: "insert type=live_summary" },
    ],
  },
  {
    id: "consultation-end-prescription",
    title: "Consultation End + Prescription",
    description: "Medical closure, report generation, and prescription delivery.",
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
    title: "Post-Consultation Follow-Up",
    description: "Automated reminders and recovery monitoring.",
    status: "next",
    impactedTables: [
      { table: "followup_tasks", eventLabel: "insert follow-up workflow tasks" },
      { table: "sms_messages", eventLabel: "insert type=followup" },
      { table: "call_records", eventLabel: "insert outbound follow-up call" },
    ],
  },
];
