const BANDS = [
  ["Wind (mph)", "<25", "25–34", "35–44", "45–54", "≥55"],
  ["Rain (in/hr)", "<0.10", "0.10–0.25", "0.25–0.50", "0.50–1.00", ">1.00"],
  ["Snow (in/hr)", "<0.5", "0.5–1.0", "1.0–2.0", "2.0–3.0", ">3.0"],
];

/** The rules behind every result, so that a recommendation can be checked. */
export function RiskGuide() {
  return (
    <details className="risk-guide">
      <summary>How risk is scored</summary>
      <table>
        <thead>
          <tr>
            <th scope="col">Condition</th>
            <th scope="col">Low</th>
            <th scope="col">Moderate</th>
            <th scope="col">High</th>
            <th scope="col">Severe</th>
            <th scope="col">No Travel</th>
          </tr>
        </thead>
        <tbody>
          {BANDS.map(([name, ...values]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              {values.map((value) => <td key={value}>{value}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        A checkpoint takes the worst of the three. Heavy loads raise wind risk: 35–44 mph over
        40,000 lb is Severe, and 45–54 mph over 30,000 lb is No Travel.
      </p>
      <p>
        Routes are ranked by fewest No Travel miles, then Severe miles, High miles, average risk,
        and finally drive time. A route with any No Travel miles is never recommended.
      </p>
    </details>
  );
}
