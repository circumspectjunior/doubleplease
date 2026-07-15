import { useEffect, useMemo, useState } from "react";
import { getCalibration, getLeagues, getShortlist, getStatus } from "./api";
import Header from "./components/Header";
import LeagueFilter from "./components/LeagueFilter";
import PickCard from "./components/PickCard";
import Bench from "./components/Bench";
import CalibrationSection from "./components/CalibrationChart";
import Disclaimer from "./components/Disclaimer";
import "./App.css";

export default function App() {
  const [leagues, setLeagues] = useState([]);
  const [status, setStatus] = useState(null);
  const [activeLeague, setActiveLeague] = useState("");
  const [sortBy, setSortBy] = useState("edge");
  const [shortlist, setShortlist] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getLeagues().then(setLeagues).catch(() => {});
    getStatus().then(setStatus).catch(() => {});
    getCalibration().then(setCalibration).catch(() => {});
  }, []);

  useEffect(() => {
    setShortlist(null);
    setError(null);
    getShortlist(activeLeague, 30)
      .then(setShortlist)
      .catch(() => setError("Couldn't reach the API. Is uvicorn running on :8000?"));
  }, [activeLeague]);

  const sortedTrusted = useMemo(() => {
    if (!shortlist) return [];
    const picks = [...shortlist.trusted];
    if (sortBy === "date") {
      picks.sort((a, b) => a.match_date.localeCompare(b.match_date));
    } else {
      picks.sort((a, b) => b.edge - a.edge);
    }
    return picks;
  }, [shortlist, sortBy]);

  return (
    <div className="app">
      <Header status={status} />

      <main className="app__main">
        <LeagueFilter leagues={leagues} active={activeLeague} onChange={setActiveLeague} />

        <div className="sort-row">
          <span className="sort-row__label">Sort by</span>
          <div className="sort-row__options">
            <button
              type="button"
              className={sortBy === "edge" ? "is-active" : ""}
              onClick={() => setSortBy("edge")}
            >
              Edge
            </button>
            <button
              type="button"
              className={sortBy === "date" ? "is-active" : ""}
              onClick={() => setSortBy("date")}
            >
              Kickoff date
            </button>
          </div>
        </div>

        {error && <p className="app__error">{error}</p>}

        {!error && !shortlist && <p className="app__loading">Loading this week's shortlist…</p>}

        {shortlist && sortedTrusted.length === 0 && (
          <p className="app__empty">
            No fixtures currently clear both the edge and data-reliability bar
            {activeLeague ? ` for ${activeLeague}` : ""}.
          </p>
        )}

        {shortlist && sortedTrusted.length > 0 && (
          <ol className="pick-list">
            {sortedTrusted.map((pick, index) => (
              <PickCard key={`${pick.match_date}-${pick.home_team}-${pick.away_team}`} rank={index + 1} pick={pick} />
            ))}
          </ol>
        )}

        {shortlist && <Bench picks={shortlist.excluded} />}

        <CalibrationSection results={calibration} />
      </main>

      <Disclaimer />
    </div>
  );
}
