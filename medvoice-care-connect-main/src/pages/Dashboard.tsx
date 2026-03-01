import { addDays, differenceInHours, format, parseISO } from "date-fns";
import { enUS } from "date-fns/locale";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  PhoneCall,
  RefreshCcw,
  Siren,
  Stethoscope,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  fetchAgendaAppointments,
  fetchDashboardAppointments,
  fetchDashboardOverview,
  fetchDashboardPatients,
  type DashboardOverviewData,
  type DashboardPatientRecord,
} from "@/services/careDataApi";
import { type Appointment } from "@/data/mockData";

type InsightSeverity = "critical" | "warning" | "info";

interface DashboardInsight {
  id: string;
  severity: InsightSeverity;
  title: string;
  detail: string;
  ctaLabel?: string;
  ctaPath?: string;
}

const statusLabel: Record<string, string> = {
  upcoming: "Upcoming",
  "in-progress": "In progress",
  done: "Completed",
};

const statusClass: Record<string, string> = {
  upcoming: "bg-primary/10 text-primary border-primary/20",
  "in-progress": "bg-warning/10 text-warning border-warning/20",
  done: "bg-success/10 text-success border-success/20",
};

const insightStyles: Record<InsightSeverity, string> = {
  critical: "bg-destructive/10 text-destructive border-destructive/20",
  warning: "bg-warning/10 text-warning border-warning/20",
  info: "bg-primary/10 text-primary border-primary/20",
};

function urgencyClass(value: number): string {
  if (value >= 8) return "text-destructive";
  if (value >= 6) return "text-warning";
  return "text-primary";
}

function parseAppointmentDateTime(appointment: Appointment): Date | null {
  if (!appointment.date || !appointment.time) return null;
  try {
    return parseISO(`${appointment.date}T${appointment.time}:00`);
  } catch {
    return null;
  }
}

function formatRatio(numerator: number, denominator: number): string {
  if (denominator <= 0) return "0%";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const pageNow = useMemo(() => new Date(), []);
  const todayKey = format(pageNow, "yyyy-MM-dd");

  const [overview, setOverview] = useState<DashboardOverviewData | null>(null);
  const [patients, setPatients] = useState<DashboardPatientRecord[]>([]);
  const [agendaAppointments, setAgendaAppointments] = useState<Appointment[]>([]);
  const [todayAppointments, setTodayAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    let active = true;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const dateFrom = todayKey;
        const dateTo = format(addDays(parseISO(`${todayKey}T00:00:00`), 14), "yyyy-MM-dd");
        const [overviewData, patientsData, agendaData, dayData] = await Promise.all([
          fetchDashboardOverview(todayKey),
          fetchDashboardPatients(),
          fetchAgendaAppointments(dateFrom, dateTo),
          fetchDashboardAppointments(todayKey),
        ]);
        if (!active) return;
        setOverview(overviewData);
        setPatients(patientsData);
        setAgendaAppointments(agendaData);
        setTodayAppointments(dayData);
      } catch (err) {
        if (!active) return;
        console.error("Failed to load dashboard command center:", err);
        setError("Some dashboard insights could not be loaded.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [todayKey, refreshCounter]);

  const callbackTasks = useMemo(() => overview?.callbackTasks ?? [], [overview?.callbackTasks]);
  const priorityQueue = useMemo(() => overview?.priorityQueue ?? [], [overview?.priorityQueue]);
  const nextAppointments = useMemo(() => overview?.nextAppointments ?? [], [overview?.nextAppointments]);
  const kpis = useMemo(
    () => overview?.kpis ?? {
      appointmentsToday: 0,
      callsToday: 0,
      cancellationsToday: 0,
      pendingCallbacks: 0,
    },
    [overview?.kpis]
  );

  const todayStatus = useMemo(() => {
    return todayAppointments.reduce(
      (acc, appointment) => {
        if (appointment.status === "done") acc.done += 1;
        if (appointment.status === "in-progress") acc.inProgress += 1;
        if (appointment.status === "upcoming") acc.upcoming += 1;
        return acc;
      },
      { done: 0, inProgress: 0, upcoming: 0 }
    );
  }, [todayAppointments]);

  const callbackAnalysis = useMemo(() => {
    const now = new Date();
    const overdue = callbackTasks.filter((task) => {
      const scheduledAt = parseISO(task.scheduledAt);
      return scheduledAt.getTime() < now.getTime();
    });
    const dueInTwoHours = callbackTasks.filter((task) => {
      const scheduledAt = parseISO(task.scheduledAt);
      const hours = differenceInHours(scheduledAt, now);
      return hours >= 0 && hours <= 2;
    });
    return {
      overdue,
      dueInTwoHours,
      slaRiskRatio: callbackTasks.length > 0 ? overdue.length / callbackTasks.length : 0,
    };
  }, [callbackTasks]);

  const priorityAnalysis = useMemo(() => {
    const high = priorityQueue.filter((item) => item.urgencyScore >= 8);
    const medium = priorityQueue.filter((item) => item.urgencyScore >= 6 && item.urgencyScore < 8);
    const symptoms = new Map<string, number>();
    priorityQueue.forEach((item) => {
      item.symptoms.forEach((symptom) => {
        symptoms.set(symptom, (symptoms.get(symptom) || 0) + 1);
      });
    });
    const topSymptoms = Array.from(symptoms.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 5);

    return { high, medium, topSymptoms };
  }, [priorityQueue]);

  const capacityAnalysis = useMemo(() => {
    const now = new Date();
    const perDay = new Map<string, number>();
    const perDoctor = new Map<string, number>();
    const motifDistribution = new Map<string, number>();
    let next48h = 0;

    agendaAppointments.forEach((appointment) => {
      perDay.set(appointment.date, (perDay.get(appointment.date) || 0) + 1);
      perDoctor.set(appointment.doctor, (perDoctor.get(appointment.doctor) || 0) + 1);
      motifDistribution.set(appointment.motif, (motifDistribution.get(appointment.motif) || 0) + 1);

      const appointmentAt = parseAppointmentDateTime(appointment);
      if (!appointmentAt) return;
      const hoursUntil = differenceInHours(appointmentAt, now);
      if (hoursUntil >= 0 && hoursUntil <= 48) next48h += 1;
    });

    const dayLoad = Array.from(perDay.entries())
      .sort((left, right) => left[0].localeCompare(right[0]))
      .slice(0, 10);
    const doctorLoad = Array.from(perDoctor.entries()).sort((left, right) => right[1] - left[1]);
    const topMotifs = Array.from(motifDistribution.entries()).sort((left, right) => right[1] - left[1]).slice(0, 4);

    return {
      dayLoad,
      doctorLoad,
      topMotifs,
      next48h,
      busiestDay: dayLoad.reduce<[string, number] | null>((best, current) => {
        if (!best || current[1] > best[1]) return current;
        return best;
      }, null),
    };
  }, [agendaAppointments]);

  const cohortAnalysis = useMemo(() => {
    const total = patients.length;
    const withAllergies = patients.filter((patient) => patient.allergies.length > 0).length;
    const withChronicHistory = patients.filter((patient) => patient.antecedents.length > 0).length;
    const withUpcomingPlan = patients.filter((patient) => (patient.upcomingAppointmentsCount || 0) > 0).length;
    const highFollowupNeed = patients.filter((patient) => (patient.upcomingAppointmentsCount || 0) >= 2).length;
    return {
      total,
      withAllergies,
      withChronicHistory,
      withUpcomingPlan,
      highFollowupNeed,
      continuityCoverage: formatRatio(withUpcomingPlan, total),
    };
  }, [patients]);

  const insights = useMemo<DashboardInsight[]>(() => {
    const generated: DashboardInsight[] = [];

    if (callbackAnalysis.overdue.length > 0) {
      const sample = callbackAnalysis.overdue[0];
      generated.push({
        id: "callbacks-overdue",
        severity: "critical",
        title: `${callbackAnalysis.overdue.length} overdue callback(s) need escalation`,
        detail: `Oldest pending callback belongs to ${sample.patientName}.`,
        ctaLabel: "Open patient",
        ctaPath: `/patients/${encodeURIComponent(sample.patientId)}`,
      });
    }

    if (priorityAnalysis.high.length > 0) {
      const sample = priorityAnalysis.high[0];
      generated.push({
        id: "high-urgency-cases",
        severity: "critical",
        title: `${priorityAnalysis.high.length} high-urgency case(s) in queue`,
        detail: `${sample.patientName} is flagged at urgency ${sample.urgencyScore}/10.`,
        ctaLabel: "Review patient",
        ctaPath: `/patients/${encodeURIComponent(sample.patientId)}`,
      });
    }

    if (kpis.cancellationsToday > 0 && kpis.appointmentsToday > 0) {
      const cancellationRate = kpis.cancellationsToday / kpis.appointmentsToday;
      if (cancellationRate >= 0.2) {
        generated.push({
          id: "cancellation-pressure",
          severity: "warning",
          title: "High cancellation pressure today",
          detail: `${formatRatio(kpis.cancellationsToday, kpis.appointmentsToday)} of today's appointments were cancelled.`,
          ctaLabel: "Open agenda",
          ctaPath: "/agenda",
        });
      }
    }

    if (cohortAnalysis.total > 0 && cohortAnalysis.withUpcomingPlan / cohortAnalysis.total < 0.5) {
      generated.push({
        id: "continuity-gap",
        severity: "warning",
        title: "Care continuity gap detected",
        detail: `Only ${cohortAnalysis.continuityCoverage} of tracked patients currently have an upcoming visit.`,
        ctaLabel: "Review patients",
        ctaPath: "/patients",
      });
    }

    if (generated.length === 0) {
      generated.push({
        id: "stable-operations",
        severity: "info",
        title: "Operational flow is stable",
        detail: "No critical operational or clinical bottlenecks detected from current data.",
      });
    }

    return generated.slice(0, 5);
  }, [callbackAnalysis, priorityAnalysis, kpis, cohortAnalysis]);

  const immediateQueue = useMemo(() => {
    return nextAppointments.slice(0, 6);
  }, [nextAppointments]);

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
            <h1 className="text-2xl font-semibold text-foreground">Clinical Operations Command Center</h1>
            <p className="text-sm text-muted-foreground mt-1">
            {format(pageNow, "EEEE, MMM d yyyy", { locale: enUS })} · live operational and clinical intelligence
            </p>
          </div>
        <Button variant="outline" className="gap-2" onClick={() => setRefreshCounter((value) => value + 1)}>
          <RefreshCcw className="h-4 w-4" />
          Refresh insights
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Today throughput</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : `${todayStatus.done}/${todayAppointments.length}`}</p>
          <p className="text-xs text-muted-foreground mt-1">
            completed · {todayStatus.inProgress} in progress · {todayStatus.upcoming} upcoming
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Callback SLA risk</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : `${Math.round(callbackAnalysis.slaRiskRatio * 100)}%`}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {callbackAnalysis.overdue.length} overdue · {callbackAnalysis.dueInTwoHours.length} due in 2h
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Clinical urgency load</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : priorityQueue.length}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {priorityAnalysis.high.length} high · {priorityAnalysis.medium.length} moderate
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Care continuity coverage</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : cohortAnalysis.continuityCoverage}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {cohortAnalysis.withUpcomingPlan}/{cohortAnalysis.total} patients with future appointments
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Cancellation pressure</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : formatRatio(kpis.cancellationsToday, Math.max(kpis.appointmentsToday, 1))}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {kpis.cancellationsToday} cancelled out of {kpis.appointmentsToday} today
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Next 48h schedule load</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : capacityAnalysis.next48h}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {capacityAnalysis.busiestDay ? `Busiest day: ${capacityAnalysis.busiestDay[0]} (${capacityAnalysis.busiestDay[1]})` : "No booked slots"}
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">Actionable insights</h2>
        </div>
        <div className="space-y-2">
          {insights.map((insight) => (
            <div key={insight.id} className="rounded-md border border-border px-3 py-2.5 flex items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={`text-[10px] ${insightStyles[insight.severity]}`}>
                    {insight.severity}
                  </Badge>
                  <p className="text-sm font-medium text-foreground">{insight.title}</p>
                </div>
                <p className="text-xs text-muted-foreground">{insight.detail}</p>
              </div>
              {insight.ctaPath && insight.ctaLabel && (
                <Button size="sm" variant="outline" onClick={() => navigate(insight.ctaPath || "/")}>
                  {insight.ctaLabel}
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Siren className="h-4 w-4 text-warning" />
            <h2 className="text-sm font-medium">Clinical priority queue</h2>
          </div>
          {priorityQueue.length === 0 && (
            <p className="text-sm text-muted-foreground">No priority cases detected.</p>
          )}
          {priorityQueue.slice(0, 5).map((item) => (
            <div key={item.id} className="rounded-md border border-border px-3 py-2.5 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">{item.patientName}</p>
                <p className={`text-xs font-semibold ${urgencyClass(item.urgencyScore)}`}>
                  Urgency {item.urgencyScore}/10
                </p>
              </div>
              {item.symptoms.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {item.symptoms.slice(0, 4).map((symptom) => (
                    <Badge key={symptom} variant="secondary" className="text-[10px]">
                      {symptom}
                    </Badge>
                  ))}
                </div>
              )}
              {item.summary && <p className="text-xs text-muted-foreground">{item.summary}</p>}
              <div className="flex gap-2 pt-1">
                <Button size="sm" variant="outline" onClick={() => navigate(`/patients/${encodeURIComponent(item.patientId)}`)}>
                  Open patient
                </Button>
                {item.appointmentId && (
                  <Button size="sm" onClick={() => navigate(`/appointments/${item.appointmentId}`)}>
                    Appointment
                  </Button>
                )}
              </div>
            </div>
          ))}
          {priorityAnalysis.topSymptoms.length > 0 && (
            <div className="pt-1">
              <p className="text-xs text-muted-foreground mb-2">Most frequent high-risk symptoms</p>
              <div className="space-y-1.5">
                {priorityAnalysis.topSymptoms.map(([label, count]) => (
                  <div key={label} className="flex items-center justify-between text-xs">
                    <span className="text-foreground">{label}</span>
                    <span className="text-muted-foreground">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <PhoneCall className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-medium">Callback command center</h2>
          </div>
          {callbackTasks.length === 0 && (
            <p className="text-sm text-muted-foreground">No pending callbacks.</p>
          )}
          {callbackTasks.slice(0, 6).map((task) => (
            <div key={task.id} className="rounded-md border border-border px-3 py-2.5 space-y-1.5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-foreground">{task.patientName}</p>
                <Badge variant="outline" className="text-xs bg-secondary text-primary border-primary/20">
                  {task.status}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {task.patientPhone} · scheduled {format(parseISO(task.scheduledAt), "dd MMM yyyy HH:mm", { locale: enUS })}
              </p>
              {task.notes && <p className="text-xs text-muted-foreground">{task.notes}</p>}
              <div className="flex gap-2 pt-1">
                <Button size="sm" variant="outline" onClick={() => navigate(`/patients/${encodeURIComponent(task.patientId)}`)}>
                  Open patient
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Stethoscope className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">Immediate queue (now and next)</h2>
        </div>
        {immediateQueue.length === 0 && (
          <p className="text-sm text-muted-foreground">No upcoming appointments.</p>
        )}
        <div className="space-y-2">
          {immediateQueue.map((appointment, index) => (
            <button
              key={appointment.id}
              onClick={() => navigate(`/appointments/${appointment.id}`)}
              className="w-full text-left rounded-md border border-border px-3 py-2.5 hover:border-primary/30"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{appointment.patientName}</p>
                  <p className="text-xs text-muted-foreground truncate">
                    {appointment.motif} · {format(parseISO(appointment.date), "dd MMM yyyy", { locale: enUS })} {appointment.time}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={statusClass[appointment.status] || ""}>
                    {statusLabel[appointment.status] || appointment.status}
                  </Badge>
                  {index === 0 && (
                    <Badge className="bg-success/10 text-success border-success/20 gap-1">
                      <Clock3 className="h-3 w-3" />
                      Next
                    </Badge>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {!loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {insights.some((item) => item.severity === "critical") ? (
            <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          )}
          Dashboard is now aggregating live operational, clinical, capacity, and cohort signals.
        </div>
      )}
    </div>
  );
}
