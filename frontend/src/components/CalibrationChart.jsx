import { useState } from "react";

const SIZE = 220;
const PAD = 28;
const PLOT = SIZE - PAD * 2;

function toX(value) {
  return PAD + value * PLOT;
}
function toY(value) {
  return PAD + (1 - value) * PLOT;
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

function MiniCalibrationChart({ result }) {
  const [hovered, setHovered] = useState(null);
  const points = result.buckets;
  const linePath = points.map((b, i) => `${i === 0 ? "M" : "L"} ${toX(b.mean_predicted)} ${toY(b.actual_hit_rate)}`).join(" ");

  return (
    <div className="calibration-card">
      <div className="calibration-card__heading">
        <h3>{result.league}</h3>
        <span className="mono calibration-card__ece">ECE {result.expected_calibration_error.toFixed(3)}</span>
      </div>

      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        width="100%"
        role="img"
        aria-label={`Calibration chart for ${result.league}: predicted probability vs actual hit rate`}
      >
        {TICKS.map((t) => (
          <g key={t}>
            <line x1={toX(t)} y1={toY(0)} x2={toX(t)} y2={toY(1)} className="calibration-card__grid" />
            <line x1={toX(0)} y1={toY(t)} x2={toX(1)} y2={toY(t)} className="calibration-card__grid" />
          </g>
        ))}

        {/* perfect-calibration reference */}
        <line
          x1={toX(0)}
          y1={toY(0)}
          x2={toX(1)}
          y2={toY(1)}
          className="calibration-card__reference"
        />

        <path d={linePath} className="calibration-card__line" fill="none" />

        {points.map((b, i) => (
          <g
            key={i}
            onPointerEnter={() => setHovered(i)}
            onPointerLeave={() => setHovered(null)}
            onFocus={() => setHovered(i)}
            onBlur={() => setHovered(null)}
            tabIndex={0}
            aria-label={`Bucket ${Math.round(b.bucket_low * 100)}-${Math.round(b.bucket_high * 100)}%: predicted ${Math.round(b.mean_predicted * 100)}%, actual ${Math.round(b.actual_hit_rate * 100)}%, n=${b.count}`}
          >
            {/* enlarged transparent hit area - the group above owns the hover/focus
                state so it doesn't matter which sibling paints on top */}
            <circle cx={toX(b.mean_predicted)} cy={toY(b.actual_hit_rate)} r="12" fill="transparent" />
            <circle
              cx={toX(b.mean_predicted)}
              cy={toY(b.actual_hit_rate)}
              r="5"
              className="calibration-card__dot"
              stroke="var(--card)"
              strokeWidth="2"
            />
          </g>
        ))}
      </svg>

      {hovered !== null && (
        <div className="calibration-card__tooltip">
          <strong>
            {Math.round(points[hovered].bucket_low * 100)}-{Math.round(points[hovered].bucket_high * 100)}%
            bucket
          </strong>
          <span>n={points[hovered].count}</span>
          <span>predicted {Math.round(points[hovered].mean_predicted * 100)}%</span>
          <span>actual {Math.round(points[hovered].actual_hit_rate * 100)}%</span>
        </div>
      )}
    </div>
  );
}

function CalibrationTable({ results }) {
  return (
    <div className="calibration-table-wrap">
      <table className="calibration-table">
        <thead>
          <tr>
            <th>League</th>
            <th>Bucket</th>
            <th>n</th>
            <th>Predicted</th>
            <th>Actual</th>
          </tr>
        </thead>
        <tbody>
          {results.flatMap((result) =>
            result.buckets.map((b, i) => (
              <tr key={`${result.league}-${i}`}>
                <td>{result.league}</td>
                <td className="mono">
                  {Math.round(b.bucket_low * 100)}-{Math.round(b.bucket_high * 100)}%
                </td>
                <td className="mono">{b.count}</td>
                <td className="mono">{Math.round(b.mean_predicted * 100)}%</td>
                <td className="mono">{Math.round(b.actual_hit_rate * 100)}%</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function CalibrationSection({ results }) {
  const [asTable, setAsTable] = useState(false);

  if (!results || results.length === 0) return null;

  return (
    <section className="calibration">
      <div className="calibration__heading">
        <div>
          <h2>Is the model actually calibrated?</h2>
          <p className="calibration__subtitle">
            Trained on {results[0].train_seasons.join("+")}, tested against the held-out{" "}
            {results[0].test_season} season. Each dot is a probability bucket - on the diagonal
            means "of matches predicted at X%, X% actually happened." Lower ECE is better.
          </p>
        </div>
        <button type="button" className="calibration__toggle" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>

      {asTable ? (
        <CalibrationTable results={results} />
      ) : (
        <div className="calibration-grid">
          {results.map((result) => (
            <MiniCalibrationChart key={result.league} result={result} />
          ))}
        </div>
      )}
    </section>
  );
}
