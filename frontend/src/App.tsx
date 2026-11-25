import { Route, Routes, Link } from 'react-router-dom';
import Header from './components/Header';
import Dashboard from './pages/Dashboard';
import Wizard from './pages/Wizard';
import Detail from './pages/Detail';
import Initiative from './pages/Initiative';
import Monitoring from './pages/Monitoring';
import SettingsPage from './pages/Settings';

export default function App() {
  return (
    <>
      <Header />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/monitoraggio" element={<Monitoring />} />
          <Route path="/nuovo" element={<Wizard />} />
          <Route path="/iniziativa/:id" element={<Initiative />} />
          <Route path="/cg/:id" element={<Detail />} />
          <Route path="/impostazioni" element={<SettingsPage />} />
          <Route
            path="*"
            element={
              <div className="card empty">
                <h2>Pagina non trovata</h2>
                <p>La pagina richiesta non esiste.</p>
                <Link to="/" className="btn primary">Torna alla dashboard</Link>
              </div>
            }
          />
        </Routes>
      </main>
      <footer className="app-footer">
        <span className="footer-mark" aria-hidden />
        Lutech · Marketing Competence Center — Control Group Facilitator
      </footer>
    </>
  );
}
