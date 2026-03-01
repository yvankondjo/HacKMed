import { type Medication } from "@/data/mockData";

export interface ConsultationSummaryRequest {
  appointmentId: string;
  patientId: string;
  transcript: Array<{
    speaker: "Doctor" | "Patient";
    text: string;
    timestamp: string;
  }>;
  soap?: Record<string, unknown>;
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
  contextSignals?: string[];
}

interface DemoScenario {
  key: string;
  keywords: string[];
  summary: string;
  detectedSymptoms: string[];
  diagnoses: string[];
  medications: Medication[];
  additionalAdvice: string[];
  suggestedQuestions: string[];
  redFlags: string[];
}

const demoScenarios: DemoScenario[] = [
  {
    key: "pharyngitis",
    keywords: ["throat", "swallow", "tonsil", "fever", "lymph"],
    summary:
      "Patient reports sore throat with fever and painful swallowing. Clinical picture is compatible with acute pharyngitis and requires bacterial vs viral assessment.",
    detectedSymptoms: ["Sore throat", "Fever", "Painful swallowing", "Neck tenderness"],
    diagnoses: [
      "Acute bacterial pharyngitis",
      "Acute viral pharyngitis",
      "Upper respiratory tract infection",
    ],
    medications: [
      { name: "Amoxicillin", dosage: "1 g", frequency: "3 times daily", duration: "6 days" },
      { name: "Paracetamol", dosage: "1000 mg", frequency: "Every 6h as needed", duration: "5 days" },
      { name: "Benzydamine throat spray", dosage: "2 sprays", frequency: "3 times daily", duration: "5 days" },
    ],
    additionalAdvice: [
      "Increase hydration and avoid throat irritants.",
      "Seek reassessment if fever persists beyond 48 hours.",
      "Return urgently for breathing difficulty or inability to swallow fluids.",
    ],
    suggestedQuestions: [
      "When did the sore throat begin and how has it evolved?",
      "What was the highest measured temperature?",
      "Any shortness of breath, drooling, or muffled voice?",
      "Do you have allergies to penicillin or other antibiotics?",
    ],
    redFlags: ["Airway compromise symptoms (dyspnea, drooling, voice change)."],
  },
  {
    key: "asthma",
    keywords: ["asthma", "wheez", "inhaler", "dyspnea", "shortness of breath"],
    summary:
      "Patient describes worsening respiratory symptoms with recurrent wheezing and increased rescue inhaler use, suggesting uncontrolled asthma flare.",
    detectedSymptoms: ["Wheezing", "Shortness of breath", "Night symptoms", "Rescue inhaler overuse"],
    diagnoses: ["Asthma exacerbation", "Poorly controlled persistent asthma", "Lower respiratory infection (to exclude)"],
    medications: [
      { name: "Salbutamol", dosage: "100 mcg", frequency: "1-2 puffs as needed", duration: "5 days" },
      { name: "Prednisone", dosage: "40 mg", frequency: "Once daily", duration: "5 days" },
    ],
    additionalAdvice: [
      "Check inhaler technique and spacer use.",
      "Monitor peak flow twice daily during the next week.",
      "Seek urgent care if breathlessness worsens or speaking is difficult.",
    ],
    suggestedQuestions: [
      "How often are you using your rescue inhaler each day?",
      "Are symptoms waking you up at night?",
      "Any trigger exposure (allergens, smoke, exercise, infection)?",
      "Have you had prior ICU admissions or intubation for asthma?",
    ],
    redFlags: ["Severe dyspnea, inability to speak full sentences, cyanosis."],
  },
  {
    key: "migraine",
    keywords: ["migraine", "headache", "photophobia", "nausea", "aura"],
    summary:
      "Patient presents with recurrent headache episodes associated with migraine features and reduced response to baseline analgesics.",
    detectedSymptoms: ["Headache", "Photophobia", "Nausea", "Recurrent attacks"],
    diagnoses: ["Migraine without aura", "Migraine with aura", "Tension-type headache (differential)"],
    medications: [
      { name: "Sumatriptan", dosage: "50 mg", frequency: "At onset, may repeat once", duration: "As needed" },
      { name: "Paracetamol", dosage: "1000 mg", frequency: "Every 6h as needed", duration: "3 days" },
    ],
    additionalAdvice: [
      "Maintain hydration and regular sleep schedule.",
      "Track triggers and attack duration in a headache diary.",
      "Seek urgent care for sudden severe headache or neurological deficits.",
    ],
    suggestedQuestions: [
      "How many headache days do you have per month?",
      "Do you notice visual aura, numbness, or speech difficulty?",
      "What triggers seem to precipitate attacks?",
      "What medications have you used in the last 24 hours?",
    ],
    redFlags: ["Thunderclap headache or focal neurological deficit."],
  },
  {
    key: "lumbar-pain",
    keywords: ["back pain", "lumbar", "sciatica", "radiating", "leg pain"],
    summary:
      "Patient reports mechanical low-back pain with possible radicular component after effort, without clear immediate neurological compromise.",
    detectedSymptoms: ["Low-back pain", "Radiation to leg", "Functional limitation"],
    diagnoses: ["Lumbar strain", "Lumbosciatica", "Disc herniation (to evaluate)"],
    medications: [
      { name: "Physiotherapy sessions", dosage: "10 sessions", frequency: "2 sessions per week", duration: "5 weeks" },
      { name: "Paracetamol", dosage: "1000 mg", frequency: "Every 8h as needed", duration: "5 days" },
      { name: "Ibuprofen", dosage: "400 mg", frequency: "3 times daily with meals", duration: "5 days" },
    ],
    additionalAdvice: [
      "Relative rest for 24-48h then progressive mobility.",
      "Start physiotherapy quickly and continue as prescribed.",
      "Avoid heavy lifting until pain improves.",
      "Urgent reassessment for weakness, saddle anesthesia, or bladder/bowel changes.",
    ],
    suggestedQuestions: [
      "Did pain start after a specific movement or trauma?",
      "Do you have numbness, weakness, or tingling in the leg?",
      "Any urinary retention, incontinence, or saddle anesthesia?",
      "What positions worsen or relieve the pain?",
    ],
    redFlags: ["Cauda equina signs or progressive motor deficit."],
  },
];

const defaultScenario: DemoScenario = {
  key: "general",
  keywords: [],
  summary:
    "Consultation transcript was captured successfully. The current information supports a non-emergency outpatient follow-up with targeted symptom clarification.",
  detectedSymptoms: ["General symptom report"],
  diagnoses: ["Primary diagnosis pending full clinical assessment"],
  medications: [{ name: "Paracetamol", dosage: "500-1000 mg", frequency: "Every 6h as needed", duration: "3 days" }],
  additionalAdvice: [
    "Ensure hydration and symptom monitoring over the next 48 hours.",
    "Return early for worsening pain, high fever, or new concerning symptoms.",
  ],
  suggestedQuestions: [
    "Can you describe exactly when symptoms started?",
    "How severe are the symptoms on a scale from 0 to 10?",
    "Do you have any medication allergies or chronic conditions?",
    "What treatments have you already tried?",
  ],
  redFlags: [],
};

function normalizeTranscript(req: ConsultationSummaryRequest): string {
  return req.transcript
    .map((entry) => entry.text.toLowerCase())
    .join(" ")
    .trim();
}

function selectDemoScenario(req: ConsultationSummaryRequest): DemoScenario {
  const text = normalizeTranscript(req);
  if (!text) return defaultScenario;

  let bestScenario = defaultScenario;
  let bestScore = 0;

  for (const scenario of demoScenarios) {
    const score = scenario.keywords.reduce((acc, keyword) => (
      text.includes(keyword) ? acc + 1 : acc
    ), 0);
    if (score > bestScore) {
      bestScenario = scenario;
      bestScore = score;
    }
  }

  return bestScore > 0 ? bestScenario : defaultScenario;
}

function buildContextSignals(soap?: Record<string, unknown>): string[] {
  if (!soap || typeof soap !== "object") return [];
  const signals: string[] = [];

  if (typeof soap.subjective === "string" && soap.subjective.trim()) {
    signals.push("SOAP subjective note was incorporated.");
  }
  if (typeof soap.objective === "string" && soap.objective.trim()) {
    signals.push("SOAP objective findings were incorporated.");
  }
  if (typeof soap.assessment === "string" && soap.assessment.trim()) {
    signals.push("SOAP assessment informed diagnostic ranking.");
  }
  if (typeof soap.plan === "string" && soap.plan.trim()) {
    signals.push("SOAP plan informed treatment recommendation.");
  }

  return signals;
}

function detectDynamicRedFlags(transcriptText: string): string[] {
  const rules: Array<{ pattern: RegExp; message: string }> = [
    { pattern: /\b(chest pain|chest pressure)\b/, message: "Possible cardiac red flag: chest pain reported." },
    { pattern: /\b(faint|syncope|passed out)\b/, message: "Syncope/presyncope mentioned and needs escalation check." },
    { pattern: /\b(confusion|seizure|weakness one side)\b/, message: "Neurological warning signs were detected." },
    { pattern: /\b(breathless at rest|cannot breathe|severe shortness of breath)\b/, message: "Severe respiratory distress signal detected." },
  ];

  return rules
    .filter((rule) => rule.pattern.test(transcriptText))
    .map((rule) => rule.message);
}

/**
 * Posts the transcript to the consultation summary API.
 * Falls back to a deterministic demo scenario when backend APIs are unavailable.
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
    const scenario = selectDemoScenario(req);
    const contextSignals = buildContextSignals(req.soap);
    await new Promise((r) => setTimeout(r, 1200));
    return {
      summary: scenario.summary,
      detectedSymptoms: scenario.detectedSymptoms,
      diagnoses: scenario.diagnoses,
      prescription: {
        medications: scenario.medications,
        additionalAdvice: scenario.additionalAdvice,
      },
      contextSignals,
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
    const joined = normalizeTranscript(req);
    const scenario = selectDemoScenario(req);
    const redFlags = [...scenario.redFlags, ...detectDynamicRedFlags(joined)];
    const askedTopics: string[] = [];
    if (/\b(since|start|started|days|weeks|months)\b/.test(joined)) askedTopics.push("duration");
    if (/\b(pain|severity|intensity|scale)\b/.test(joined)) askedTopics.push("severity");
    if (/\b(allergy|allergies|allergic)\b/.test(joined)) askedTopics.push("allergies");
    if (/\b(fever|temperature)\b/.test(joined)) askedTopics.push("fever");

    return {
      questions: scenario.suggestedQuestions,
      redFlags: Array.from(new Set(redFlags)),
      askedTopics,
    };
  }
}
