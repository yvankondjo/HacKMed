import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { appointments, patients } from "@/data/mockData";

const statusConfig: Record<string, { label: string; borderColor: string; dotColor: string; badgeBg: string; badgeText: string }> = {
  upcoming: {
    label: "À venir",
    borderColor: "border-l-primary",
    dotColor: "bg-primary",
    badgeBg: "bg-secondary",
    badgeText: "text-primary",
  },
  "in-progress": {
    label: "En cours",
    borderColor: "border-l-warning",
    dotColor: "bg-warning",
    badgeBg: "bg-[#FEF3C7]",
    badgeText: "text-[#B45309]",
  },
  done: {
    label: "Terminé",
    borderColor: "border-l-muted-foreground/40",
    dotColor: "bg-muted-foreground/40",
    badgeBg: "bg-muted",
    badgeText: "text-muted-foreground",
  },
};

function getInitials(name: string) {
  return name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);
}

function getInitialsBg(patientId: string) {
  const colors = [
    "bg-primary/10 text-primary",
    "bg-[#F3E8FF] text-[#7C3AED]",
    "bg-[#FEF3C7] text-[#B45309]",
    "bg-[#FCE7F3] text-[#DB2777]",
  ];
  return colors[parseInt(patientId, 10) % colors.length];
}

export default function Dashboard() {
  const navigate = useNavigate();
  const today = new Date();

  const todayAppts = appointments
    .filter((a) => a.date === format(today, "yyyy-MM-dd"))
    .sort((a, b) => a.time.localeCompare(b.time));

  const now = format(today, "HH:mm");
  const nextUpcomingId = todayAppts.find((a) => a.status === "upcoming" && a.time >= now)?.id;

  const dayStartHour = 8;
  const dayEndHour = 18;
  const currentHour = today.getHours() + today.getMinutes() / 60;
  const dayProgress = Math.max(0, Math.min(100, ((currentHour - dayStartHour) / (dayEndHour - dayStartHour)) * 100));
  const timeMarkers = Array.from({ length: dayEndHour - dayStartHour + 1 }, (_, i) => dayStartHour + i);

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-foreground">
          {format(today, "EEEE d MMMM", { locale: fr })}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {todayAppts.length} rendez-vous aujourd'hui
        </p>
      </div>

      {/* Day progress bar */}
      <div className="space-y-1.5">
        <div className="relative h-1.5 rounded-full bg-muted overflow-visible">
          {todayAppts.map((a) => {
            const [h, m] = a.time.split(":").map(Number);
            const pos = ((h + m / 60 - dayStartHour) / (dayEndHour - dayStartHour)) * 100;
            if (pos < 0 || pos > 100) return null;
            const cfg = statusConfig[a.status];
            return (
              <div
                key={a.id}
                className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full ${cfg.dotColor} ring-2 ring-background`}
                style={{ left: `${pos}%` }}
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
          {timeMarkers.filter((_, i) => i % 2 === 0).map((h) => (
            <span key={h} className="text-[10px] text-muted-foreground font-mono">
              {String(h).padStart(2, "0")}:00
            </span>
          ))}
        </div>
      </div>

      {/* Appointment cards */}
      <div className="space-y-2">
        {todayAppts.map((a) => {
          const status = statusConfig[a.status];
          const isNext = a.id === nextUpcomingId;
          return (
            <button
              key={a.id}
              onClick={() => navigate(`/appointments/${a.id}`)}
              className={`
                w-full text-left px-4 py-3.5 rounded-lg border border-border shadow-[0_1px_3px_rgba(0,0,0,0.08)]
                border-l-[3px] ${status.borderColor}
                hover:shadow-[0_2px_8px_rgba(0,0,0,0.1)] transition-all duration-150 group flex items-center gap-4
                ${isNext ? "bg-secondary" : "bg-card"}
              `}
            >
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 ${getInitialsBg(a.patientId)}`}>
                {getInitials(a.patientName)}
              </div>
              <div className="text-sm font-mono text-muted-foreground w-12 shrink-0">
                {a.time}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-foreground text-sm">{a.patientName}</p>
                <p className="text-sm text-muted-foreground truncate">{a.motif}</p>
              </div>
              <div className={`flex items-center gap-1.5 shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium ${status.badgeBg} ${status.badgeText}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${status.dotColor}`} />
                {status.label}
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
            </button>
          );
        })}

        {todayAppts.length === 0 && (
          <div className="text-center py-16 text-muted-foreground text-sm">
            Aucun rendez-vous aujourd'hui
          </div>
        )}
      </div>
    </div>
  );
}
