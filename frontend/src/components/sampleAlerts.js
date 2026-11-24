/**
 * Static sample alerts for demonstration. They look like the agent's advisory alerts, but they are fixed examples:
 * they are not stored, never sent to the server, and cannot be acknowledged, resolved or verified. Every card carries
 * a Sample tag, and the counts say how many of their alerts are samples.
 * Timestamps are placed relative to the moment the page loads, so the examples always look recent.
 */
const minutesAgo = (m) => new Date(Date.now() - m * 60_000).toISOString();
const details = (likely_cause, evidence) => JSON.stringify({ likely_cause, evidence });

export const SAMPLE_ALERTS = [
  {
    id: "sample-1", source: "sample", sample: true, status: "OPEN", severity: "MEDIUM",
    utility_type: "COMPRESSED_AIR", plant_id: "PLANT-01", zone: "Hall B", assigned_to: "facilities",
    title: "Compressed air: flow up 14% vs history",
    recommendation: "Inspect the area for leaks or open drains, compare against the production schedule and confirm the meter.",
    details: details("Higher demand than this series' history: typically a leak, an open drain or uncontrolled demand.",
      { recent_mean: 71.7, baseline_mean: 62.9, change_pct: 14.0, z_score: 5.1 }),
    status_note: null,
    created_at: minutesAgo(310), acknowledged_at: null, resolved_at: null, verified_at: null,
  },
  {
    id: "sample-2", source: "sample", sample: true, status: "ACKNOWLEDGED", severity: "HIGH",
    utility_type: "CHILLED_WATER", plant_id: "PLANT-01", zone: "Chiller plant", assigned_to: "maintenance",
    title: "Chilled water: temperature up 11% vs history",
    recommendation: "Inspect the cooling and heat-exchange equipment and check the temperature sensor calibration.",
    details: details("Temperature moved away from its usual level: a heat-exchanger or cooling problem, or sensor drift.",
      { recent_mean: 14.4, baseline_mean: 13.0, change_pct: 11.0, z_score: 4.6 }),
    status_note: null,
    created_at: minutesAgo(240), acknowledged_at: minutesAgo(218), resolved_at: null, verified_at: null,
  },
  {
    id: "sample-3", source: "sample", sample: true, status: "RESOLVED", severity: "MEDIUM",
    utility_type: "NITROGEN", plant_id: "PLANT-01", zone: "Packing line", assigned_to: "facilities",
    title: "Nitrogen: flow down 9% vs history",
    recommendation: "Confirm the production schedule. If production was normal, check the line and the meter.",
    details: details("Demand fell versus history: a lower production load, a blocked line or a meter or sensor fault.",
      { recent_mean: 58.4, baseline_mean: 64.2, change_pct: -9.0, z_score: -4.2 }),
    status_note: "Purge schedule was changed for a short run; flow is back to normal.",
    created_at: minutesAgo(1400), acknowledged_at: minutesAgo(1385), resolved_at: minutesAgo(1260), verified_at: null,
  },
  {
    id: "sample-4", source: "sample", sample: true, status: "VERIFIED", severity: "MEDIUM",
    utility_type: "PROCESS_WATER", plant_id: "PLANT-01", zone: "Utility room", assigned_to: "maintenance",
    title: "Process water: pressure down 7% vs history",
    recommendation: "Check supply capacity, filters, regulators and leaks, and review with the certified operator.",
    details: details("Supply pressure is lower than usual: a capacity shortfall, a restriction or a leak.",
      { recent_mean: 5.58, baseline_mean: 6.0, change_pct: -7.0, z_score: -4.4 }),
    status_note: "Return to normal verified from the last 48 hours of telemetry (9 readings).",
    created_at: minutesAgo(6000), acknowledged_at: minutesAgo(5980), resolved_at: minutesAgo(5940), verified_at: minutesAgo(5920),
  },
];
