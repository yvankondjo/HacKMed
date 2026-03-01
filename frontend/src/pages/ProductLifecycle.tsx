import { CheckCircle2, Clock3, Database, PhoneCall, Timer } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { productLifecycleStages } from "@/data/mockData";
import { fetchLifecycleStages } from "@/services/lifecycleApi";

const statusStyles = {
  done: {
    dot: "bg-success",
    badge: "bg-success/10 text-success border-success/20",
    label: "Done",
  },
  active: {
    dot: "bg-primary animate-pulse",
    badge: "bg-primary/10 text-primary border-primary/20",
    label: "In progress",
  },
  next: {
    dot: "bg-muted-foreground/40",
    badge: "bg-muted text-muted-foreground border-border",
    label: "Upcoming",
  },
} as const;

export default function ProductLifecycle() {
  const { data, isLoading } = useQuery({
    queryKey: ["lifecycle-stages"],
    queryFn: fetchLifecycleStages,
  });

  const stages = data?.stages ?? productLifecycleStages;
  const totalTableEvents = stages.reduce((count, stage) => count + stage.impactedTables.length, 0);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardContent className="p-5 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">Lifecycle stages</p>
              <p className="text-2xl font-semibold">{stages.length}</p>
            </div>
            <Timer className="h-5 w-5 text-primary" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">Table/event impacts</p>
              <p className="text-2xl font-semibold">{totalTableEvents}</p>
            </div>
            <Database className="h-5 w-5 text-primary" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">Primary channel</p>
              <p className="text-2xl font-semibold">Voice + SMS</p>
            </div>
            <PhoneCall className="h-5 w-5 text-primary" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-xl">Patient product lifecycle</CardTitle>
          <p className="text-sm text-muted-foreground">
            Tables created/updated at each stage of the care journey.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading && (
            <div className="text-sm text-muted-foreground">Loading stages...</div>
          )}
          {stages.map((stage, index) => {
            const status = statusStyles[stage.status];
            return (
              <div key={stage.id} className="relative pl-6">
                {index < stages.length - 1 && (
                  <div className="absolute left-[11px] top-6 h-[calc(100%+0.75rem)] w-px bg-border" />
                )}
                <div className={`absolute left-0 top-1 h-3 w-3 rounded-full ${status.dot}`} />
                <div className="rounded-lg border border-border bg-card p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold">{stage.title}</h3>
                    <Badge variant="outline" className={status.badge}>
                      {stage.status === "done" ? (
                        <CheckCircle2 className="h-3 w-3 mr-1" />
                      ) : (
                        <Clock3 className="h-3 w-3 mr-1" />
                      )}
                      {status.label}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">{stage.description}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {stage.impactedTables.map((impact) => (
                      <div
                        key={`${stage.id}-${impact.table}-${impact.eventLabel}`}
                        className="rounded-md border border-border bg-muted px-2.5 py-1.5 text-xs"
                      >
                        <span className="font-semibold text-foreground">{impact.table}</span>
                        <span className="text-muted-foreground"> : {impact.eventLabel}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
