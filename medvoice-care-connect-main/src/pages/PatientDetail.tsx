import { useEffect, useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CalendarClock, Loader2, Phone } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchPatientDetail,
  type DashboardPatientDetail,
} from "@/services/careDataApi";

const statusClass: Record<string, string> = {
  upcoming: "bg-primary/10 text-primary border-primary/20",
  "in-progress": "bg-warning/10 text-warning border-warning/20",
  done: "bg-success/10 text-success border-success/20",
};

export default function PatientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<DashboardPatientDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const run = async () => {
      if (!id) {
        setLoading(false);
        return;
      }
      try {
        const value = await fetchPatientDetail(decodeURIComponent(id));
        if (active) setDetail(value);
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [id]);

  const patient = detail?.patient;
  const appointments = detail?.appointments || [];
  const calls = detail?.calls || [];

  const age = useMemo(() => {
    if (!patient?.dateOfBirth) return null;
    const birth = new Date(patient.dateOfBirth).getTime();
    if (!Number.isFinite(birth)) return null;
    return Math.floor((Date.now() - birth) / (365.25 * 24 * 60 * 60 * 1000));
  }, [patient?.dateOfBirth]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-3">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Chargement du dossier patient...</p>
      </div>
    );
  }

  if (!patient) {
    return (
      <div className="space-y-4 py-12 text-center">
        <p className="text-sm text-muted-foreground">Patient introuvable.</p>
        <Button variant="outline" onClick={() => navigate("/patients")}>Retour</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <button
        onClick={() => navigate("/patients")}
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Retour patients
      </button>

      <Card>
        <CardHeader>
          <CardTitle>{patient.firstName} {patient.lastName}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {age !== null ? `${age} ans` : "Âge inconnu"} · {patient.phone} · {patient.email}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">Groupe sanguin: {patient.bloodType || "Unknown"}</p>
          <div className="flex flex-wrap gap-2">
            {patient.allergies.length > 0 ? patient.allergies.map((allergy) => (
              <Badge key={allergy} variant="destructive">{allergy}</Badge>
            )) : <Badge variant="outline">No allergies recorded</Badge>}
          </div>
          <div className="flex flex-wrap gap-2">
            {patient.antecedents.length > 0 ? patient.antecedents.map((condition) => (
              <Badge key={condition} variant="secondary">{condition}</Badge>
            )) : <Badge variant="outline">No conditions recorded</Badge>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Appointments</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {appointments.length === 0 && (
            <p className="text-sm text-muted-foreground">No appointment history.</p>
          )}
          {appointments.map((appointment) => (
            <button
              key={appointment.id}
              onClick={() => navigate(`/appointments/${appointment.id}`)}
              className="w-full text-left rounded-lg border border-border px-4 py-3 hover:border-primary/30"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-foreground">{appointment.motif}</p>
                  <p className="text-xs text-muted-foreground">
                    {format(parseISO(appointment.date), "dd MMM yyyy", { locale: fr })} · {appointment.time} · {appointment.doctor}
                  </p>
                </div>
                <Badge variant="outline" className={statusClass[appointment.status] || ""}>{appointment.status}</Badge>
              </div>
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Call Records</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {calls.length === 0 && (
            <p className="text-sm text-muted-foreground">No call records.</p>
          )}
          {calls.map((call) => (
            <div key={call.id} className="rounded-lg border border-border p-4 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-foreground flex items-center gap-2">
                  <Phone className="h-3.5 w-3.5" /> {call.motif}
                </p>
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <CalendarClock className="h-3.5 w-3.5" />
                  {format(parseISO(call.date), "dd MMM yyyy", { locale: fr })} · {call.duration}
                </p>
              </div>
              {call.summary && <p className="text-sm text-muted-foreground">{call.summary}</p>}
              {call.symptoms.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {call.symptoms.map((symptom) => (
                    <Badge key={symptom} variant="secondary">{symptom}</Badge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
