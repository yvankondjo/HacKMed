import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Calendar, Phone, FileText, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/contexts/AuthContext";
import { appointments, calls, pastAppointments, mockAIPrescription } from "@/data/mockData";

const statusConfig: Record<string, { label: string; class: string }> = {
  upcoming: { label: "À venir", class: "bg-primary/10 text-primary border-primary/20" },
  "in-progress": { label: "En cours", class: "bg-warning/10 text-warning border-warning/20" },
  done: { label: "Terminé", class: "bg-success/10 text-success border-success/20" },
};

export default function PatientDashboard() {
  const { user } = useAuth();
  const patientId = user?.patientId || "1";
  const today = new Date();

  // Filter data for this patient
  const myAppointments = appointments.filter((a) => a.patientId === patientId);
  const myPastAppointments = pastAppointments[patientId] || [];
  const myCalls = calls.filter((c) => c.patientId === patientId);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">
          Bonjour, {user?.name}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {format(today, "EEEE d MMMM yyyy", { locale: fr })}
        </p>
      </div>

      <Tabs defaultValue="appointments" className="space-y-4">
        <TabsList className="bg-card border border-border">
          <TabsTrigger value="appointments" className="gap-2 text-sm">
            <Calendar className="h-3.5 w-3.5" />
            Rendez-vous
          </TabsTrigger>
          <TabsTrigger value="calls" className="gap-2 text-sm">
            <Phone className="h-3.5 w-3.5" />
            Appels
          </TabsTrigger>
          <TabsTrigger value="prescriptions" className="gap-2 text-sm">
            <FileText className="h-3.5 w-3.5" />
            Ordonnances
          </TabsTrigger>
        </TabsList>

        {/* ─── Rendez-vous ─── */}
        <TabsContent value="appointments" className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Mes rendez-vous</h2>
          {myAppointments.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-12">Aucun rendez-vous prévu.</p>
          )}
          {myAppointments.map((a) => {
            const status = statusConfig[a.status];
            return (
              <div
                key={a.id}
                className="p-4 rounded-lg bg-card border border-border flex items-center gap-4"
              >
                <div className="text-sm font-mono text-muted-foreground w-12 shrink-0">
                  {a.time}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-foreground text-sm">{a.motif}</p>
                  <p className="text-sm text-muted-foreground">{a.doctor} · {a.doctorSpecialty}</p>
                </div>
                <Badge variant="outline" className={`${status.class} text-xs shrink-0`}>
                  {status.label}
                </Badge>
              </div>
            );
          })}

          {myPastAppointments.length > 0 && (
            <>
              <h2 className="text-sm font-medium text-muted-foreground mt-6 mb-3">Historique</h2>
              {myPastAppointments.map((h, i) => (
                <div key={i} className="p-4 rounded-lg bg-card border border-border flex items-center gap-4">
                  <div className="text-xs font-mono text-muted-foreground w-20 shrink-0">
                    {format(new Date(h.date), "dd MMM yy", { locale: fr })}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-foreground text-sm">{h.motif}</p>
                    <p className="text-sm text-muted-foreground">{h.summary}</p>
                  </div>
                </div>
              ))}
            </>
          )}
        </TabsContent>

        {/* ─── Appels ─── */}
        <TabsContent value="calls" className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Mes appels</h2>
          {myCalls.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-12">Aucun appel enregistré.</p>
          )}
          {myCalls.map((c) => (
            <div key={c.id} className="p-4 rounded-lg bg-card border border-border space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Phone className="h-4 w-4 text-primary" />
                  <span className="text-sm font-medium text-foreground">{c.motif}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {c.duration} · {format(new Date(c.date), "dd MMM yyyy", { locale: fr })}
                </div>
              </div>
              <p className="text-sm text-muted-foreground">{c.summary}</p>
              {c.symptoms.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {c.symptoms.map((s) => (
                    <Badge key={s} variant="secondary" className="text-xs">{s}</Badge>
                  ))}
                </div>
              )}
              {c.recommendations.length > 0 && (
                <div className="pt-1">
                  <p className="text-xs text-muted-foreground mb-1">Recommandations :</p>
                  <ul className="space-y-0.5">
                    {c.recommendations.map((r, i) => (
                      <li key={i} className="text-xs text-foreground/80">• {r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </TabsContent>

        {/* ─── Ordonnances ─── */}
        <TabsContent value="prescriptions" className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Mes ordonnances</h2>
          {/* Mock: show one prescription for done appointments */}
          {myAppointments.filter((a) => a.status === "done").length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-12">Aucune ordonnance disponible.</p>
          ) : (
            myAppointments
              .filter((a) => a.status === "done")
              .map((a) => (
                <div key={a.id} className="p-4 rounded-lg bg-card border border-border space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-foreground">{a.motif}</p>
                      <p className="text-xs text-muted-foreground">
                        {a.doctor} · {format(new Date(a.date), "dd MMM yyyy", { locale: fr })}
                      </p>
                    </div>
                    <Badge className="bg-success/10 text-success border-success/20 text-xs">Validée</Badge>
                  </div>
                  <div className="space-y-2">
                    {mockAIPrescription.medications.map((med, i) => (
                      <div key={i} className="p-3 rounded bg-muted/30 border border-border">
                        <p className="text-sm font-medium text-foreground">{med.name} — {med.dosage}</p>
                        <p className="text-xs text-muted-foreground">{med.frequency} · {med.duration}</p>
                      </div>
                    ))}
                  </div>
                  {mockAIPrescription.additionalAdvice.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Conseils :</p>
                      <ul className="space-y-0.5">
                        {mockAIPrescription.additionalAdvice.map((a, i) => (
                          <li key={i} className="text-xs text-foreground/80">• {a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
