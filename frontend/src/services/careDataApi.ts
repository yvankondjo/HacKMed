import { format } from "date-fns";
import {
  appointments as mockAppointments,
  calls as mockCalls,
  pastAppointments as mockPastAppointments,
  patients as mockPatients,
  type Appointment,
  type CallRecord,
  type PastAppointment,
  type Patient,
} from "@/data/mockData";

interface DashboardAppointmentsResponse {
  appointments: Appointment[];
}

interface DashboardKpisApi {
  appointmentsToday: number;
  callsToday: number;
  cancellationsToday: number;
  pendingCallbacks: number;
}

interface DashboardCallbackTaskApi {
  id: string;
  patientId: string;
  patientName: string;
  patientPhone: string;
  scheduledAt: string;
  notes?: string | null;
  status: string;
}

interface DashboardPriorityItemApi {
  id: string;
  patientId: string;
  patientName: string;
  patientPhone: string;
  appointmentId?: string | null;
  urgencyScore: number;
  symptoms: string[];
  summary: string;
  createdAt: string;
}

interface DashboardOverviewResponse {
  kpis: DashboardKpisApi;
  callbackTasks: DashboardCallbackTaskApi[];
  priorityQueue: DashboardPriorityItemApi[];
  nextAppointments: Appointment[];
}

interface DashboardPatientApi {
  id: string;
  firstName: string;
  lastName: string;
  dateOfBirth: string | null;
  phone: string;
  email: string;
  bloodType: string | null;
  allergies: string[];
  antecedents: string[];
  lastAppointmentDate: string | null;
  lastAppointmentMotif: string | null;
  upcomingAppointmentsCount: number;
}

interface DashboardPatientsResponse {
  patients: DashboardPatientApi[];
}

interface DashboardAppointmentDetailResponse {
  appointment: Appointment;
  patient: DashboardPatientApi;
  history: PastAppointment[];
  calls: CallRecord[];
}

interface CancelAppointmentResponse {
  appointmentId: string;
  status: "cancelled";
  callbackScheduled: boolean;
  callbackTaskId?: string | null;
  callbackScheduledAt?: string | null;
  patientId?: string | null;
  patientPhone?: string | null;
}

interface DashboardPatientDetailResponse {
  patient: DashboardPatientApi;
  appointments: Appointment[];
  calls: CallRecord[];
}

export interface DashboardPatientRecord extends Patient {
  lastAppointmentDate?: string | null;
  lastAppointmentMotif?: string | null;
  upcomingAppointmentsCount?: number;
}

export interface DashboardAppointmentDetail {
  appointment: Appointment;
  patient: DashboardPatientRecord;
  history: PastAppointment[];
  calls: CallRecord[];
}

export interface DashboardOverviewData {
  kpis: DashboardKpisApi;
  callbackTasks: DashboardCallbackTaskApi[];
  priorityQueue: DashboardPriorityItemApi[];
  nextAppointments: Appointment[];
}

export interface DashboardPatientDetail {
  patient: DashboardPatientRecord;
  appointments: Appointment[];
  calls: CallRecord[];
}

function normalizePatient(record: DashboardPatientApi): DashboardPatientRecord {
  return {
    id: record.id,
    firstName: record.firstName,
    lastName: record.lastName,
    dateOfBirth: record.dateOfBirth ?? "",
    phone: record.phone,
    email: record.email,
    bloodType: record.bloodType ?? "Unknown",
    allergies: record.allergies ?? [],
    antecedents: record.antecedents ?? [],
    lastAppointmentDate: record.lastAppointmentDate,
    lastAppointmentMotif: record.lastAppointmentMotif,
    upcomingAppointmentsCount: record.upcomingAppointmentsCount ?? 0,
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed for ${url} (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function fetchDashboardAppointments(date?: string): Promise<Appointment[]> {
  const effectiveDate = date ?? format(new Date(), "yyyy-MM-dd");
  try {
    const payload = await fetchJson<DashboardAppointmentsResponse>(
      `/api/dashboard/appointments?date=${encodeURIComponent(effectiveDate)}`
    );
    return payload.appointments;
  } catch {
    return mockAppointments.filter((item) => item.date === effectiveDate);
  }
}

export async function fetchDashboardOverview(date?: string): Promise<DashboardOverviewData> {
  const effectiveDate = date ?? format(new Date(), "yyyy-MM-dd");
  try {
    return await fetchJson<DashboardOverviewResponse>(
      `/api/dashboard/overview?date=${encodeURIComponent(effectiveDate)}`
    );
  } catch {
    const todayAppointments = mockAppointments.filter((item) => item.date === effectiveDate);
    return {
      kpis: {
        appointmentsToday: todayAppointments.length,
        callsToday: mockCalls.length,
        cancellationsToday: 0,
        pendingCallbacks: 0,
      },
      callbackTasks: [],
      priorityQueue: mockCalls
        .filter((item) => item.urgencyScore >= 5)
        .map((item) => {
          const patient = mockPatients.find((row) => row.id === item.patientId);
          return {
            id: item.id,
            patientId: item.patientId,
            patientName: patient ? `${patient.firstName} ${patient.lastName}` : "Unknown Patient",
            patientPhone: patient?.phone || "",
            appointmentId: item.appointmentId,
            urgencyScore: item.urgencyScore,
            symptoms: item.symptoms,
            summary: item.summary,
            createdAt: item.date,
          };
        }),
      nextAppointments: mockAppointments.filter((item) => item.status !== "done").slice(0, 8),
    };
  }
}

export async function fetchAgendaAppointments(
  dateFrom?: string,
  dateTo?: string
): Promise<Appointment[]> {
  const params = new URLSearchParams();
  if (dateFrom) params.set("dateFrom", dateFrom);
  if (dateTo) params.set("dateTo", dateTo);
  const query = params.toString();

  try {
    const payload = await fetchJson<DashboardAppointmentsResponse>(
      `/api/dashboard/agenda${query ? `?${query}` : ""}`
    );
    return payload.appointments;
  } catch {
    return mockAppointments.filter((item) => item.status !== "done");
  }
}

export async function fetchDashboardPatients(): Promise<DashboardPatientRecord[]> {
  try {
    const payload = await fetchJson<DashboardPatientsResponse>("/api/dashboard/patients");
    return payload.patients.map(normalizePatient);
  } catch {
    return mockPatients;
  }
}

export async function fetchAppointmentDetail(
  appointmentId: string
): Promise<DashboardAppointmentDetail | null> {
  try {
    const payload = await fetchJson<DashboardAppointmentDetailResponse>(
      `/api/dashboard/appointments/${encodeURIComponent(appointmentId)}`
    );
    return {
      appointment: payload.appointment,
      patient: normalizePatient(payload.patient),
      history: payload.history || [],
      calls: payload.calls || [],
    };
  } catch {
    const appointment = mockAppointments.find((item) => item.id === appointmentId);
    if (!appointment) return null;
    const patient = mockPatients.find((item) => item.id === appointment.patientId);
    if (!patient) return null;
    return {
      appointment,
      patient,
      history: mockPastAppointments[patient.id] || [],
      calls: mockCalls.filter((item) => item.appointmentId === appointment.id),
    };
  }
}

export async function cancelDashboardAppointment(
  appointmentId: string,
  reason?: string
): Promise<CancelAppointmentResponse> {
  const response = await fetch(`/api/dashboard/appointments/${encodeURIComponent(appointmentId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to cancel appointment (${response.status})`);
  }
  return (await response.json()) as CancelAppointmentResponse;
}

export async function fetchPatientDetail(
  patientId: string
): Promise<DashboardPatientDetail | null> {
  try {
    const payload = await fetchJson<DashboardPatientDetailResponse>(
      `/api/dashboard/patients/${encodeURIComponent(patientId)}`
    );
    return {
      patient: normalizePatient(payload.patient),
      appointments: payload.appointments || [],
      calls: payload.calls || [],
    };
  } catch {
    const patient = mockPatients.find((item) => item.id === patientId);
    if (!patient) return null;
    return {
      patient,
      appointments: mockAppointments.filter((item) => item.patientId === patient.id),
      calls: mockCalls.filter((item) => item.patientId === patient.id),
    };
  }
}
