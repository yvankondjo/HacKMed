import { useEffect, useMemo, useState } from "react";
import { addDays, format, parseISO } from "date-fns";
import { enUS } from "date-fns/locale";
import { CalendarClock, UserRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type Appointment } from "@/data/mockData";
import {
  cancelDashboardAppointment,
  fetchAgendaAppointments,
} from "@/services/careDataApi";

const statusConfig: Record<Appointment["status"], { label: string; className: string }> = {
  upcoming: {
    label: "Upcoming",
    className: "bg-primary/10 text-primary border-primary/20",
  },
  "in-progress": {
    label: "In progress",
    className: "bg-warning/10 text-warning border-warning/20",
  },
  done: {
    label: "Completed",
    className: "bg-muted text-muted-foreground border-border",
  },
};

export default function Agenda() {
  const navigate = useNavigate();
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const run = async () => {
      try {
        const from = format(new Date(), "yyyy-MM-dd");
        const to = format(addDays(new Date(), 30), "yyyy-MM-dd");
        const rows = await fetchAgendaAppointments(from, to);
        if (active) setAppointments(rows);
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();

    return () => {
      active = false;
    };
  }, []);

  const groupedByDate = useMemo(() => {
    const grouped: Record<string, Appointment[]> = {};
    for (const appointment of appointments) {
      if (!grouped[appointment.date]) grouped[appointment.date] = [];
      grouped[appointment.date].push(appointment);
    }
    Object.values(grouped).forEach((rows) => rows.sort((a, b) => a.time.localeCompare(b.time)));
    return Object.entries(grouped).sort(([left], [right]) => left.localeCompare(right));
  }, [appointments]);

  const cancelAppointment = async (appointment: Appointment) => {
    try {
      setCancellingId(appointment.id);
      const response = await cancelDashboardAppointment(
        appointment.id,
        "Cancelled by doctor from agenda"
      );
      setAppointments((prev) => prev.filter((item) => item.id !== appointment.id));
      if (response.callbackScheduled) {
        toast.success("Appointment cancelled. Callback task created to reschedule the patient.");
      } else {
        toast.success("Appointment cancelled.");
      }
    } catch (err) {
      toast.error("Unable to cancel appointment.");
    } finally {
      setCancellingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Agenda</h1>
        <p className="text-sm text-muted-foreground mt-1">Upcoming appointments (next 30 days)</p>
      </div>

      {loading && (
        <p className="text-sm text-muted-foreground">Loading agenda...</p>
      )}

      {!loading && groupedByDate.length === 0 && (
        <p className="text-sm text-muted-foreground">No appointments scheduled.</p>
      )}

      <div className="space-y-5">
        {groupedByDate.map(([date, rows]) => (
          <div key={date} className="space-y-2">
            <div className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 text-primary" />
              <h2 className="font-medium text-foreground">
                {format(parseISO(date), "EEEE d MMMM yyyy", { locale: enUS })}
              </h2>
            </div>

            <div className="space-y-2">
              {rows.map((appointment) => {
                const status = statusConfig[appointment.status];
                return (
                  <div
                    key={appointment.id}
                    onClick={() => navigate(`/appointments/${appointment.id}`)}
                    className="rounded-lg border border-border bg-card px-4 py-3 flex items-center gap-4 cursor-pointer hover:border-primary/30 transition-colors"
                  >
                    <div className="text-sm font-mono text-muted-foreground w-14 shrink-0">
                      {appointment.time}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{appointment.motif}</p>
                      <p className="text-xs text-muted-foreground flex items-center gap-1.5 mt-0.5">
                        <UserRound className="h-3.5 w-3.5" />
                        {appointment.patientName} · {appointment.doctor}
                      </p>
                    </div>
                    <Badge variant="outline" className={`${status.className} text-xs`}>
                      {status.label}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={cancellingId === appointment.id}
                      onClick={(event) => {
                        event.stopPropagation();
                        void cancelAppointment(appointment);
                      }}
                      className="text-destructive border-destructive/40 hover:bg-destructive/5"
                    >
                      {cancellingId === appointment.id ? "Cancelling..." : "Cancel"}
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
