import { SidebarProvider } from "@/components/ui/sidebar";
import { PatientSidebar } from "@/components/PatientSidebar";

export function PatientLayout({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full">
        <PatientSidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <header className="h-12 border-b border-border bg-card flex items-center justify-end px-4 shrink-0" />
          <main className="flex-1 overflow-auto p-6">
            {children}
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}
