import { patients, pastAppointments } from "@/data/mockData";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { User, Droplets, AlertTriangle, Calendar } from "lucide-react";
import { format, differenceInYears, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

export default function Patients() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Patients</h1>

      <div className="grid gap-4">
        {patients.map((p) => {
          const age = differenceInYears(new Date(), parseISO(p.dateOfBirth));
          const history = pastAppointments[p.id] || [];

          return (
            <Card key={p.id} className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-4">
                  <Avatar className="h-12 w-12 border border-border">
                    <AvatarFallback className="bg-primary/10 text-primary font-semibold">
                      {p.firstName[0]}{p.lastName[0]}
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-lg">{p.firstName} {p.lastName}</CardTitle>
                    <p className="text-sm text-muted-foreground">{age} ans · {p.phone} · {p.email}</p>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Droplets className="h-4 w-4" />
                    <span className="font-medium">{p.bloodType}</span>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-3">
                {p.allergies.length > 0 && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <AlertTriangle className="h-4 w-4 text-destructive" />
                    {p.allergies.map((a) => (
                      <Badge key={a} variant="destructive" className="text-xs">{a}</Badge>
                    ))}
                  </div>
                )}

                {p.antecedents.length > 0 && (
                  <div className="flex items-start gap-2">
                    <User className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <p className="text-sm text-muted-foreground">{p.antecedents.join(" · ")}</p>
                  </div>
                )}

                {history.length > 0 && (
                  <div className="flex items-start gap-2">
                    <Calendar className="h-4 w-4 text-muted-foreground mt-0.5" />
                    <p className="text-sm text-muted-foreground">
                      Dernier RDV : {format(parseISO(history[0].date), "d MMM yyyy", { locale: fr })} — {history[0].motif}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
