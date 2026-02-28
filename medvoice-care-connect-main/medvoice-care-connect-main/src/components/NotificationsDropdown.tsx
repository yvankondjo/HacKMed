import { Bell, FileText, AlertCircle, CalendarDays } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { notifications } from "@/data/mockData";

const iconMap = {
  reminder: CalendarDays,
  document: FileText,
  alert: AlertCircle,
};

export function NotificationsDropdown() {
  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="relative p-2 rounded-lg hover:bg-muted transition-colors">
          <Bell className="h-5 w-5 text-muted-foreground" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 h-4 w-4 rounded-full bg-destructive text-destructive-foreground text-[10px] flex items-center justify-center font-bold">
              {unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="p-3 border-b border-border">
          <p className="font-semibold text-sm text-foreground">Notifications</p>
        </div>
        <div className="max-h-64 overflow-y-auto">
          {notifications.map((n) => {
            const Icon = iconMap[n.type];
            return (
              <div
                key={n.id}
                className={`flex items-start gap-3 p-3 border-b border-border last:border-0 ${
                  !n.read ? "bg-primary/5" : ""
                }`}
              >
                <Icon className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className={`text-sm ${!n.read ? "font-medium text-foreground" : "text-muted-foreground"}`}>
                    {n.message}
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">{n.date}</p>
                </div>
                {!n.read && <span className="h-2 w-2 rounded-full bg-primary shrink-0 mt-1.5" />}
              </div>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}