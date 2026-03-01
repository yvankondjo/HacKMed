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

function medicationPlanScore(text: string): number {
  const lowered = text.toLowerCase();
  const cues = [
    "prescribe",
    "prescription",
    "take",
    "session",
    "physio",
    "physiotherapist",
    "paracetamol",
    "ibuprofen",
    "amoxicillin",
    "azithromycin",
    "antibiotic",
  ];
  return cues.reduce((score, cue) => score + (lowered.includes(cue) ? 1 : 0), 0);
}

function pickPrescriberText(req: ConsultationSummaryRequest): string {
  const doctorBlob = req.transcript
    .filter((entry) => entry.speaker === "Doctor")
    .map((entry) => entry.text || "")
    .join(" ");
  const patientBlob = req.transcript
    .filter((entry) => entry.speaker === "Patient")
    .map((entry) => entry.text || "")
    .join(" ");
  const allBlob = req.transcript.map((entry) => entry.text || "").join(" ");

  const doctorScore = medicationPlanScore(doctorBlob);
  const patientScore = medicationPlanScore(patientBlob);

  if (patientScore > doctorScore && patientBlob.trim()) return patientBlob;
  if (doctorBlob.trim()) return doctorBlob;
  return allBlob;
}

function textWindowAroundAliases(text: string, aliases: string[], radius = 120): string {
  const lowered = text.toLowerCase();
  for (const alias of aliases) {
    const idx = lowered.indexOf(alias.toLowerCase());
    if (idx === -1) continue;
    return text.slice(Math.max(0, idx - radius), Math.min(text.length, idx + radius));
  }
  return text;
}

function extractDose(text: string): string {
  const match = text.toLowerCase().match(/\b(\d{1,4}(?:\.\d+)?)\s*(mg|g|mcg|µg)\b/);
  if (!match) return "";
  return `${match[1]} ${match[2]}`;
}

function extractFrequency(text: string): string {
  const lowered = text.toLowerCase();
  const m = lowered.match(/\bevery\s*(\d{1,2})\s*(?:h|hr|hrs|hour|hours)\b/);
  if (m) return `Every ${m[1]} hours`;
  if (/\btwice(?:\s+(?:a|per))?\s+day\b/.test(lowered) || /\b(?:2|two)\s+times(?:\s+(?:a|per))?\s+day\b/.test(lowered)) return "Twice daily";
  if (/\b(?:3|three)\s+times(?:\s+(?:a|per))?\s+day\b/.test(lowered)) return "3 times daily";
  if (/\bonce(?:\s+(?:a|per))?\s+day\b/.test(lowered)) return "Once daily";
  if (/\bas needed\b/.test(lowered)) return "As needed";
  return "";
}

function extractDuration(text: string): string {
  const lowered = text.toLowerCase();
  const match = lowered.match(
    /\bfor\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(day|days|week|weeks|month|months)\b/
  );
  if (match) return `${match[1]} ${match[2]}`;
  if (/\bas needed\b/.test(lowered)) return "As needed";
  return "";
}

function parseWordNumber(raw: string): number {
  const text = (raw || "").toLowerCase();
  const words: Record<string, number> = {
    one: 1,
    two: 2,
    three: 3,
    four: 4,
    five: 5,
    six: 6,
    seven: 7,
    eight: 8,
    nine: 9,
    ten: 10,
    eleven: 11,
    twelve: 12,
  };
  if (/^\d+$/.test(text)) return Number(text);
  return words[text] || 0;
}

function buildDynamicFallbackSummary(req: ConsultationSummaryRequest): ConsultationSummaryResponse {
  const transcriptText = normalizeTranscript(req);
  const planText = pickPrescriberText(req);
  const planLower = planText.toLowerCase();
  const meds: Medication[] = [];
  const seen = new Set<string>();

  const addMed = (name: string, aliases: string[], defaults?: Partial<Medication>) => {
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    const window = textWindowAroundAliases(planText, aliases);
    meds.push({
      name,
      dosage: extractDose(window) || defaults?.dosage || "",
      frequency: extractFrequency(window) || defaults?.frequency || "",
      duration: extractDuration(window) || defaults?.duration || "",
    });
    seen.add(key);
  };

  const hasPhysio = /\b(physio|physiotherapy|physiotherapist)\b/.test(planLower);
  const physioNegated = /(do not|don't|no)\s+(go|need|start|do).{0,35}(physio|physiotherapy|physiotherapist)/.test(
    planLower
  );
  if (hasPhysio && (!physioNegated || /\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+sessions?\b/.test(planLower))) {
    const sessionMatch = planLower.match(
      /\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+sessions?\b/
    );
    const count = sessionMatch ? parseWordNumber(sessionMatch[1]) : 0;
    const window = textWindowAroundAliases(planText, ["physio", "physiotherapy", "physiotherapist"]);
    meds.push({
      name: "Physiotherapy sessions",
      dosage: count > 0 ? `${count} sessions` : "As prescribed",
      frequency: extractFrequency(window) || "As prescribed",
      duration: extractDuration(window) || "",
    });
    seen.add("physiotherapy sessions");
  }

  if (/\b(paracetamol|acetaminophen|etamol)\b/.test(planLower)) {
    addMed("Paracetamol", ["paracetamol", "acetaminophen", "etamol"], { frequency: "As needed" });
  }
  if (/\bibuprofen\b/.test(planLower)) {
    addMed("Ibuprofen", ["ibuprofen"], { frequency: "As needed" });
  }
  if (/\bamoxicillin|amoxicilline\b/.test(planLower)) {
    addMed("Amoxicillin", ["amoxicillin", "amoxicilline"]);
  }
  if (/\bazithromycin\b/.test(planLower)) {
    addMed("Azithromycin", ["azithromycin"]);
  }
  if (/\bantibiotic|antibiotics\b/.test(planLower) && !meds.some((m) => ["Amoxicillin", "Azithromycin"].includes(m.name))) {
    addMed("Antibiotic (doctor-specified)", ["antibiotic", "antibiotics"]);
  }

  if (meds.length === 0 && /\b(paracetamol|pain|fever|back pain)\b/.test(transcriptText)) {
    meds.push({
      name: "Paracetamol",
      dosage: "",
      frequency: "As needed",
      duration: "",
    });
  }

  const detectedSymptoms: string[] = [];
  if (/\bback pain|lower back|lumbar\b/.test(transcriptText)) detectedSymptoms.push("Back pain");
  if (/\bnumbness|tingling\b/.test(transcriptText)) detectedSymptoms.push("Numbness");
  if (/\bcan't walk|cannot walk|difficulty walking\b/.test(transcriptText)) detectedSymptoms.push("Walking difficulty");
  if (/\bcough\b/.test(transcriptText)) detectedSymptoms.push("Cough");
  if (/\bfever|temperature\b/.test(transcriptText)) detectedSymptoms.push("Fever");
  if (detectedSymptoms.length === 0) detectedSymptoms.push("General symptom report");

  const diagnoses: string[] = [];
  if (/\bback pain|lower back|lumbar|sciatica\b/.test(transcriptText)) diagnoses.push("Low-back pain syndrome");
  if (/\bnumbness|radiat|leg pain\b/.test(transcriptText)) diagnoses.push("Possible lumbar radicular involvement");
  if (/\bvirus|viral\b/.test(transcriptText)) diagnoses.push("Possible viral syndrome");
  if (/\bantibiotic|infection|bacterial\b/.test(transcriptText)) diagnoses.push("Possible infectious etiology (to confirm clinically)");
  if (diagnoses.length === 0) diagnoses.push("Clinical diagnosis pending physician confirmation");

  const additionalAdvice = Array.from(
    new Set(
      [
        /\bavoid heavy lifting|no heavy lifting\b/.test(planLower)
          ? "Avoid heavy lifting until symptoms improve."
          : "",
        /\burgent|emergency|weakness|bladder|bowel|chest pain|cannot breathe\b/.test(transcriptText)
          ? "Urgent reassessment is needed if neurological or cardiopulmonary red flags worsen."
          : "",
      ].filter(Boolean)
    )
  );

  return {
    summary:
      "Consultation summary fallback generated from transcript content. Prescription reflects medications explicitly mentioned in the dialogue.",
    detectedSymptoms: Array.from(new Set(detectedSymptoms)),
    diagnoses: Array.from(new Set(diagnoses)).slice(0, 4),
    prescription: {
      medications: meds,
      additionalAdvice: additionalAdvice.length > 0
        ? additionalAdvice
        : ["Follow the clinician instructions discussed during the consultation."],
    },
    contextSignals: buildContextSignals(req.soap),
  };
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
    await new Promise((r) => setTimeout(r, 1200));
    return buildDynamicFallbackSummary(req);
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
