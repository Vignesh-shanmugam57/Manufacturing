/**
 * Static sample alarms, shown so the alarm panels are not empty when the plant is calm.
 *
 * They are fixed text, not telemetry: they are never sent to the server, never counted as live alerts, never
 * highlighted in the 3D view and cannot be acknowledged. Every screen that shows them labels them "Sample".
 * Equipment names match the plant model in backend/app/twin/catalog.py.
 */
export const SAMPLE_ALARMS = [
  {
    code: "SAMPLE-1",
    severity: "MAJOR",
    equipment: "Air Header - Hall A",
    title: "Possible compressed air leakage",
    actual: "6.02 bar",
    expected: "6.4 - 7.2 bar",
    recommendation: "Survey the Hall A header and drop legs for leaks, and check the compressor loading.",
  },
  {
    code: "SAMPLE-2",
    severity: "WARNING",
    equipment: "Chiller 1",
    title: "Low chilled water Delta T",
    actual: "4.1 °C",
    expected: "4.5 - 7.5 °C",
    recommendation: "Check the bypass and control valves, then balance the coil flow with the certified operator.",
  },
  {
    code: "SAMPLE-3",
    severity: "WARNING",
    equipment: "Steam Header",
    title: "Unstable steam header pressure",
    actual: "8.7 - 10.9 bar swing",
    expected: "9.1 - 10.5 bar",
    recommendation: "Review the boiler pressure control and burner tuning with the certified operator.",
  },
  {
    code: "SAMPLE-4",
    severity: "MAJOR",
    equipment: "Air Handling Unit 2",
    title: "HVAC airflow imbalance",
    actual: "13,800 m3/h",
    expected: "15,000 - 21,000 m3/h",
    recommendation: "Check the filters, dampers and fan drive, then re-balance the zone with the facilities team.",
  },
];
