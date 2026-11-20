import { Route, Routes, Link } from 'react-router-dom';
import Header from './components/Header';
import Dashboard from './pages/Dashboard';
import Wizard from './pages/Wizard';
import Detail from './pages/Detail';
import SettingsPage from './pages/Settings';

export default function App() {
  return (
    <>
      <Header />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/nuovo" element={<Wizard />} />
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
    </>
  );
}
