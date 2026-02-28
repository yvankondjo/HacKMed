import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Activity } from "lucide-react";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!phone.trim()) {
      setError("Veuillez saisir votre numéro.");
      return;
    }
    const success = login(phone);
    if (success) {
      navigate("/");
    } else {
      setError("Numéro invalide.");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-background">
      <div className="w-full max-w-sm space-y-0">
        {/* Logo area */}
        <div className="text-center space-y-3 pb-7">
          <div className="mx-auto h-11 w-11 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-foreground tracking-tight">MedVoice</h1>
            <p className="text-xs text-muted-foreground mt-1 tracking-wide">Clinical AI Assistant</p>
          </div>
        </div>

        {/* Separator */}
        <div className="w-full h-px bg-border mb-7" />

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="phone" className="text-[11px] text-muted-foreground uppercase tracking-wider font-normal">Numéro de téléphone</Label>
            <Input
              id="phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+33612345678"
              className="h-11 bg-card border-input placeholder:text-muted-foreground/50 focus-visible:ring-primary focus-visible:border-primary"
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button type="submit" className="w-full h-11 font-medium">
            Se connecter
          </Button>

          <div className="text-[11px] text-center text-muted-foreground space-y-1 pt-3">
            <p>POC user unique</p>
            <p className="text-[10px] text-muted-foreground/60 mt-1.5">Entrer simplement un numéro de téléphone</p>
          </div>
        </form>
      </div>
    </div>
  );
}
