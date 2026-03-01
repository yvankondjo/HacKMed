import { useEffect, useMemo, useState } from "react";
import { addDays, format, parseISO } from "date-fns";
import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { type Appointment } from "@/data/mockData";
import { fetchAgendaAppointments } from "@/services/careDataApi";

const statusConfig: Record<
  Appointment["status"],
  {
    label: string;
    borderColor: string;
    dotColor: string;
    badgeBg: string;
    badgeText: string;
  }
> = {
  upcoming: {
    label: "Upcoming",
    borderColor: "border-l-primary",
    dotColor: "bg-primary",
    badgeBg: "bg-secondary",
    badgeText: "text-primary",
  },
  "in-progress": {
    label: "In progress",
    borderColor: "border-l-warning",
    dotColor: "bg-warning",
    badgeBg: "bg-warning/10",
    badgeText: "text-warning",
  },
  done: {
    label: "Completed",
    borderColor: "border-l-muted-foreground/40",
    dotColor: "bg-muted-foreground/40",
    badgeBg: "bg-muted",
    badgeText: "text-muted-foreground",
  },
};

function getInitials(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

function getInitialsBg(patientId: string) {
  const colors = [
    "bg-primary/10 text-primary",
    "bg-[#F3E8FF] text-[#7C3AED]",
    "bg-[#FEF3C7] text-[#B45309]",
    "bg-[#FCE7F3] text-[#DB2777]",
  ];
  const seed = Array.from(patientId).reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return colors[seed % colors.length];
}

function toTimestamp(appointment: Appointment) {
  return new Date(`${appointment.date}T${appointment.time}:00`).getTime();
}

export default function Dashboard() {
  const navigate = useNavigate();
  const today = new Date();
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    const run = async () => {
      try {
        const now = new Date();
        const from = format(now, "yyyy-MM-dd");
        const to = format(addDays(now, 30), "yyyy-MM-dd");
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

  const todayKey = format(today, "yyyy-MM-dd");
  const nowMs = Date.now();

  const todayAppts = useMemo(
    () =>
      appointments
        .filter((appointment) => appointment.date === todayKey)
        .sort((left, right) => left.time.localeCompare(right.time)),
    [appointments, todayKey]
  );

  const closestAppts = useMemo(() => {
    const activeAppointments = appointments
      .filter((appointment) => appointment.status !== "done")
      .sort((left, right) => toTimestamp(left) - toTimestamp(right));

    const upcoming = activeAppointments.filter((appointment) => toTimestamp(appointment) >= nowMs);
    return (upcoming.length > 0 ? upcoming : activeAppointments).slice(0, 5);
  }, [appointments, nowMs]);

  const nextUpcomingId =
    closestAppts.find((appointment) => appointment.status === "upcoming")?.id ?? null;

  const dayStartHour = 8;
  const dayEndHour = 18;
  const currentHour = today.getHours() + today.getMinutes() / 60;
  const dayProgress = Math.max(
    0,
    Math.min(100, ((currentHour - dayStartHour) / (dayEndHour - dayStartHour)) * 100)
  );
  const timeMarkers = Array.from(
    { length: dayEndHour - dayStartHour + 1 },
    (_, index) => dayStartHour + index
  );

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-foreground">{format(today, "EEEE, MMMM d")}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {closestAppts.length} closest appointment{closestAppts.length !== 1 ? "s" : ""}
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="relative h-1.5 rounded-full bg-muted overflow-visible">
          {todayAppts.map((appointment) => {
            const [hour, minute] = appointment.time.split(":").map(Number);
            const position = ((hour + minute / 60 - dayStartHour) / (dayEndHour - dayStartHour)) * 100;
            if (position < 0 || position > 100) return null;

            const status = statusConfig[appointment.status];
            return (
              <div
                key={appointment.id}
                className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full ${status.dotColor} ring-2 ring-background`}
                style={{ left: `${position}%` }}
              />
            );
          })}

          {dayProgress > 0 && dayProgress < 100 && (
            <div
              className="absolute top-1/2 -translate-y-1/2 w-0.5 h-4 bg-foreground/40 rounded-full"
              style={{ left: `${dayProgress}%` }}
            />
          )}
        </div>

        <div className="flex justify-between">
          {timeMarkers
            .filter((_, index) => index % 2 === 0)
            .map((hour) => (
              <span key={hour} className="text-[10px] text-muted-foreground font-mono">
                {String(hour).padStart(2, "0")}:00
              </span>
            ))}
        </div>
      </div>

      <div className="space-y-2">
        {loading && <div className="text-sm text-muted-foreground py-4">Loading appointments...</div>}

        {!loading &&
          closestAppts.map((appointment) => {
            const status = statusConfig[appointment.status];
            const isNext = appointment.id === nextUpcomingId;
            const displayTime =
              appointment.date === todayKey
                ? appointment.time
                : `${format(parseISO(appointment.date), "MMM d")} · ${appointment.time}`;

            return (
              <button
                key={appointment.id}
                onClick={() => navigate(`/appointments/${appointment.id}`)}
                className={`
                  w-full text-left px-4 py-3.5 rounded-lg border border-border shadow-[0_1px_3px_rgba(0,0,0,0.08)]
                  border-l-[3px] ${status.borderColor}
                  hover:shadow-[0_2px_8px_rgba(0,0,0,0.1)] transition-all duration-150 group flex items-center gap-4
                  ${isNext ? "bg-secondary" : "bg-card"}
                `}
              >
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 ${getInitialsBg(appointment.patientId)}`}
                >
                  {getInitials(appointment.patientName)}
                </div>
                <div className="text-sm font-mono text-muted-foreground w-24 shrink-0">{displayTime}</div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-foreground text-sm">{appointment.patientName}</p>
                  <p className="text-sm text-muted-foreground truncate">{appointment.motif}</p>
                </div>
                <div
                  className={`flex items-center gap-1.5 shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium ${status.badgeBg} ${status.badgeText}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${status.dotColor}`} />
                  {status.label}
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
              </button>
            );
          })}

        {!loading && closestAppts.length === 0 && (
          <div className="text-center py-16 text-muted-foreground text-sm">
            No upcoming appointments
          </div>
        )}
      </div>
    </div>
  );
}
