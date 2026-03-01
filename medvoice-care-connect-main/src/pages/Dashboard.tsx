import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  PhoneCall,
  Stethoscope,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  fetchDashboardOverview,
  type DashboardOverviewData,
} from "@/services/careDataApi";

const statusLabel: Record<string, string> = {
  upcoming: "À venir",
  "in-progress": "En cours",
  done: "Terminé",
};

const statusClass: Record<string, string> = {
  upcoming: "bg-primary/10 text-primary border-primary/20",
  "in-progress": "bg-warning/10 text-warning border-warning/20",
  done: "bg-success/10 text-success border-success/20",
};

function urgencyClass(value: number): string {
  if (value >= 8) return "text-destructive";
  if (value >= 6) return "text-warning";
  return "text-primary";
}

export default function Dashboard() {
  const navigate = useNavigate();
  const today = new Date();
  const todayKey = format(today, "yyyy-MM-dd");

  const [overview, setOverview] = useState<DashboardOverviewData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const run = async () => {
      try {
        const data = await fetchDashboardOverview(todayKey);
        if (active) setOverview(data);
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [todayKey]);

  const kpis = overview?.kpis;
  const callbackTasks = overview?.callbackTasks || [];
  const priorityQueue = overview?.priorityQueue || [];
  const nextAppointments = useMemo(
    () => (overview?.nextAppointments || []).slice(0, 6),
    [overview?.nextAppointments]
  );

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-foreground">
          {format(today, "EEEE d MMMM", { locale: fr })}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Tableau de pilotage médical</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Rendez-vous aujourd'hui</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : (kpis?.appointmentsToday || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Appels aujourd'hui</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : (kpis?.callsToday || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Annulations aujourd'hui</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : (kpis?.cancellationsToday || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">Callbacks en attente</p>
          <p className="text-2xl font-semibold mt-1">{loading ? "..." : (kpis?.pendingCallbacks || 0)}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <PhoneCall className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-medium">Action Center: callbacks à faire</h2>
          </div>

          {callbackTasks.length === 0 && (
            <p className="text-sm text-muted-foreground">Aucun callback en attente.</p>
          )}

          {callbackTasks.map((task) => (
            <div key={task.id} className="rounded-md border border-border px-3 py-2.5 space-y-1.5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-foreground">{task.patientName}</p>
                <Badge variant="outline" className="text-xs bg-secondary text-primary border-primary/20">
                  {task.status}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {task.patientPhone} · prévu {format(parseISO(task.scheduledAt), "dd MMM yyyy HH:mm", { locale: fr })}
              </p>
              {task.notes && <p className="text-xs text-muted-foreground">{task.notes}</p>}
              <div className="flex gap-2 pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => navigate(`/patients/${encodeURIComponent(task.patientId)}`)}
                >
                  Ouvrir patient
                </Button>
              </div>
            </div>
          ))}
        </div>

        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            <h2 className="text-sm font-medium">Clinical Priority Queue</h2>
          </div>

          {priorityQueue.length === 0 && (
            <p className="text-sm text-muted-foreground">Aucun cas prioritaire détecté.</p>
          )}

          {priorityQueue.map((item) => (
            <div key={item.id} className="rounded-md border border-border px-3 py-2.5 space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">{item.patientName}</p>
                <p className={`text-xs font-semibold ${urgencyClass(item.urgencyScore)}`}>
                  Urgence {item.urgencyScore}/10
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
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => navigate(`/patients/${encodeURIComponent(item.patientId)}`)}
                >
                  Patient
                </Button>
                {item.appointmentId && (
                  <Button
                    size="sm"
                    onClick={() => navigate(`/appointments/${item.appointmentId}`)}
                  >
                    Rendez-vous
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">Now / Next appointments</h2>
        </div>

        {nextAppointments.length === 0 && (
          <p className="text-sm text-muted-foreground">Aucun rendez-vous à venir.</p>
        )}

        <div className="space-y-2">
          {nextAppointments.map((appointment, index) => (
            <button
              key={appointment.id}
              onClick={() => navigate(`/appointments/${appointment.id}`)}
              className="w-full text-left rounded-md border border-border px-3 py-2.5 hover:border-primary/30"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  {index === 0 ? (
                    <Stethoscope className="h-4 w-4 text-primary" />
                  ) : (
                    <Users className="h-4 w-4 text-muted-foreground" />
                  )}
                  <div>
                    <p className="text-sm font-medium text-foreground">{appointment.patientName}</p>
                    <p className="text-xs text-muted-foreground">
                      {appointment.motif} · {format(parseISO(appointment.date), "dd MMM yyyy", { locale: fr })} {appointment.time}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={statusClass[appointment.status] || ""}>
                    {statusLabel[appointment.status] || appointment.status}
                  </Badge>
                  {index === 0 && (
                    <Badge className="bg-success/10 text-success border-success/20">Now</Badge>
                  )}
                  {index === 1 && (
                    <Badge className="bg-secondary text-primary">Next</Badge>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {!loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          Dashboard linked to live backend overview.
        </div>
      )}
    </div>
  );
}
