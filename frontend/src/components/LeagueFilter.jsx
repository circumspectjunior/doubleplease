export default function LeagueFilter({ leagues, active, onChange }) {
  return (
    <div className="league-filter" role="tablist" aria-label="Filter by league">
      <button
        type="button"
        role="tab"
        aria-selected={active === ""}
        className={`league-filter__tab ${active === "" ? "is-active" : ""}`}
        onClick={() => onChange("")}
      >
        All leagues
      </button>
      {leagues.map((league) => (
        <button
          key={league.name}
          type="button"
          role="tab"
          aria-selected={active === league.name}
          className={`league-filter__tab ${active === league.name ? "is-active" : ""}`}
          onClick={() => onChange(league.name)}
        >
          {league.name}
        </button>
      ))}
    </div>
  );
}
