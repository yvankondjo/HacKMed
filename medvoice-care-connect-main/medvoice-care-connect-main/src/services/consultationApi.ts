import { type Medication } from "@/data/mockData";

export interface ConsultationSummaryRequest {
  appointmentId: string;
  patientId: string;
  transcript: Array<{
    speaker: "Doctor" | "Patient";
    text: string;
    timestamp: string;
  }>;
}

export interface SuggestQuestionsResponse {
  questions: string[];
  redFlags: string[];
  askedTopics: string[];
}

export interface ConsultationSummaryResponse {
  summary: string;
  detectedSymptoms: string[];
  diagnoses: string[];
  prescription: {
    medications: Medication[];
    additionalAdvice: string[];
  };
}

/**
 * Posts the transcript to the consultation summary API.
 * Currently returns mock data after a simulated delay.
 * Replace the body of this function with a real fetch() when the API is ready.
 */
export async function fetchConsultationSummary(
  req: ConsultationSummaryRequest
): Promise<ConsultationSummaryResponse> {
  try {
    const res = await fetch("/api/consultation/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  } catch {
    await new Promise((r) => setTimeout(r, 1200));
    return {
      summary:
        "Patient présentant une douleur pharyngée depuis 3 jours avec fièvre à 38.5°C, dysphagie et adénopathies cervicales sensibles. Tableau compatible avec une angine bactérienne.",
      detectedSymptoms: [
        "Douleur gorge",
        "Fièvre 38.5°C",
        "Dysphagie",
        "Adénopathies",
      ],
      diagnoses: [
        "Angine bactérienne (streptocoque probable)",
        "Pharyngite aiguë",
        "Infection virale des VAS",
      ],
      prescription: {
        medications: [
          { name: "Amoxicilline", dosage: "1g", frequency: "3 fois par jour", duration: "6 jours" },
          { name: "Paracétamol", dosage: "1000mg", frequency: "Toutes les 6h si douleur", duration: "5 jours" },
          { name: "Hexaspray", dosage: "2 pulvérisations", frequency: "3 fois par jour", duration: "5 jours" },
        ],
        additionalAdvice: [
          "Repos vocal recommandé",
          "Hydratation abondante (1.5L/jour minimum)",
          "Éviter les aliments irritants",
          "Reconsulter si fièvre persiste au-delà de 48h",
        ],
      },
    };
  }
}

export async function fetchSuggestedQuestions(
  req: ConsultationSummaryRequest
): Promise<SuggestQuestionsResponse> {
  try {
    const res = await fetch("/api/consultation/suggest-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  } catch {
    const joined = req.transcript.map((m) => m.text.toLowerCase()).join(" ");
    const hasFever = joined.includes("fièvre") || joined.includes("fievre");
    return {
      questions: [
        "Depuis quand exactement les symptômes ont-ils commencé ?",
        hasFever
          ? "La fièvre est-elle continue ou intermittente ?"
          : "Avez-vous eu de la fièvre, et à combien ?",
        "Sur une échelle de 0 à 10, quelle est l'intensité de la douleur ?",
        "Avez-vous des allergies médicamenteuses connues ?",
      ],
      redFlags: [],
      askedTopics: [],
    };
  }
}
