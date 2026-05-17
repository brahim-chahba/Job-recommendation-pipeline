import { useEffect, useState } from 'react'
import heroImg from './assets/hero.png'
import './App.css'

type WorkMode = 'all' | 'remote' | 'onsite' | 'hybrid'

// Types pour l'API
interface JobMatch {
  match_score: number
  title: string
  company: string
  city: string
  country: string
  work_mode: string
  job_type: string
  job_category: string
  job_url: string
  site: string
  date_posted: string
  skills: string[]
  description: string
  predicted_category?: string
}

interface ApiFilters {
  cities: string[]
  countries: string[]
  categories: string[]
  skills: string[]
  work_modes: string[]
}

const sources = ['LinkedIn', 'France Travail', 'Emploi.ma', 'Indeed']

function App() {
  const [filters, setFilters] = useState<ApiFilters | null>(null)
  const [selectedCity, setSelectedCity] = useState('Casablanca')
  const [searchTitle, setSearchTitle] = useState('Data Analyst')
  const [workMode, setWorkMode] = useState<WorkMode>('all')
  const [matches, setMatches] = useState<JobMatch[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Charger les filtres au dmarrage
  useEffect(() => {
    fetch('http://localhost:5001/api/filters')
      .then(res => res.json())
      .then(data => setFilters(data))
      .catch(err => {
        console.error("Erreur chargement filtres:", err)
        // Fallback cities
        setFilters({
          cities: ['Casablanca', 'Rabat', 'Marrakech', 'Tanger'],
          countries: ['Morocco', 'France'],
          categories: [],
          skills: [],
          work_modes: ['all', 'remote', 'hybrid', 'onsite']
        })
      })
  }, [])

  // Lancer la recherche
  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    
    setIsLoading(true)
    setError(null)
    
    try {
      // On extrait des mots cls du titre pour les passer comme skills si besoin
      const words = searchTitle.toLowerCase().split(' ')
      
      const response = await fetch('http://localhost:5001/api/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: searchTitle,
          city: selectedCity === 'Toutes' ? '' : selectedCity,
          country: 'Morocco',
          work_mode: workMode,
          skills: words, // Le modle ML va matcher ces mots avec sa base de skills
          top_n: 12
        })
      })
      
      if (!response.ok) throw new Error("Erreur lors du matching")
      
      const data = await response.json()
      setMatches(data.results || [])
    } catch (err: any) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  // Lancer une recherche initiale
  useEffect(() => {
    handleSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <main className="page-shell">
      <nav className="topbar" aria-label="Navigation principale">
        <a className="brand" href="#hero" aria-label="JobMatch Maroc">
          <span className="brand-mark">JM</span>
          <span>JobMatch AI</span>
        </a>
        <div className="nav-links">
          <a href="#search">Recherche</a>
          <a href="#sources">Sources</a>
        </div>
      </nav>

      <section className="hero-section" id="hero">
        <div className="hero-copy">
          <p className="eyebrow">Modle ML XGBoost intgr</p>
          <h1>Trouvez les offres au Maroc qui matchent vraiment votre profil.</h1>
          <p className="hero-text">
            Notre intelligence artificielle analyse plus de 3000 offres d'emploi rcentes, 
            extrait les comptences cls, et utilise un modle de Gradient Boosting pour
            vous recommander les meilleures opportunits.
          </p>
          <div className="hero-actions">
            <a className="primary-action" href="#search">Commencer</a>
            <a className="secondary-action" href="#results">Voir les offres</a>
          </div>
        </div>

        <div className="hero-panel" aria-label="Apercu du tableau de bord">
          <div className="panel-header">
            <span>Prcision IA</span>
            <strong>82%</strong>
          </div>
          <img src={heroImg} alt="" className="hero-asset" />
          <div className="floating-card">
            <span>Top ville</span>
            <strong>{selectedCity}</strong>
          </div>
          <div className="signal-grid" aria-hidden="true">
            <span className={isLoading ? "pulse" : ""}></span>
            <span className={isLoading ? "pulse" : ""}></span>
            <span className={isLoading ? "pulse" : ""}></span>
            <span className={isLoading ? "pulse" : ""}></span>
          </div>
        </div>
      </section>

      <section className="search-section" id="search">
        <div className="section-heading">
          <p className="eyebrow">Recherche intelligente</p>
          <h2>Dcrivez votre profil idal.</h2>
        </div>

        <form className="search-board" onSubmit={handleSearch}>
          <label>
            Poste ou comptences
            <input 
              type="text" 
              value={searchTitle}
              onChange={(e) => setSearchTitle(e.target.value)}
              placeholder="ex: Data Scientist Python AWS..."
            />
          </label>

          <label>
            Ville
            <select value={selectedCity} onChange={(e) => setSelectedCity(e.target.value)}>
              <option>Toutes</option>
              {filters?.cities.map((city) => (
                <option key={city} value={city}>{city}</option>
              ))}
            </select>
          </label>

          <fieldset>
            <legend>Type de travail</legend>
            <div className="mode-options">
              {(['all', 'remote', 'hybrid', 'onsite'] as WorkMode[]).map((mode) => (
                <button
                  type="button"
                  className={workMode === mode ? 'active' : ''}
                  key={mode}
                  onClick={() => setWorkMode(mode)}
                >
                  {mode === 'all' ? 'Tous' : mode === 'remote' ? 'Remote' : mode === 'hybrid' ? 'Hybride' : 'Sur site'}
                </button>
              ))}
            </div>
          </fieldset>
          
          <button type="submit" className="primary-action" disabled={isLoading} style={{ marginTop: '1rem', width: '100%' }}>
            {isLoading ? 'Analyse par l\'IA...' : 'Trouver des matchs'}
          </button>
        </form>
      </section>

      <section className="results-section" id="results">
        <div className="section-heading compact">
          <p className="eyebrow">Rsultats recommands</p>
          <h2>Top {matches.length} opportunits</h2>
        </div>

        {error && <div style={{color: 'red', textAlign: 'center'}}>{error}</div>}
        
        {isLoading && matches.length === 0 && (
          <div style={{textAlign: 'center', padding: '2rem'}}>Chargement des recommandations ML...</div>
        )}

        <div className="job-list">
          {matches.map((job, idx) => (
            <article className="job-card" key={idx}>
              <div>
                <p className="job-company">
                  {job.company || 'Entreprise Confidentielle'} 
                  {job.predicted_category && <span style={{marginLeft: 10, fontSize: '0.7em', padding: '2px 6px', background: 'var(--surface-sunken)', borderRadius: 4}}>{job.predicted_category}</span>}
                </p>
                <h3>
                  <a href={job.job_url} target="_blank" rel="noreferrer" style={{color: 'inherit', textDecoration: 'none'}}>
                    {job.title}
                  </a>
                </h3>
                <p>
                  📍 {job.city || 'Maroc'} · {job.work_mode === 'remote' ? '🏠 Remote' : job.work_mode === 'hybrid' ? '🔄 Hybride' : '🏢 Sur site'} · {job.job_type}
                </p>
                
                {job.skills && job.skills.length > 0 && (
                  <div style={{display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.8rem'}}>
                    {job.skills.slice(0, 5).map(skill => (
                      <span key={skill} style={{fontSize: '0.75rem', background: 'rgba(255,255,255,0.1)', padding: '2px 8px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.2)'}}>
                        {skill}
                      </span>
                    ))}
                    {job.skills.length > 5 && (
                      <span style={{fontSize: '0.75rem', color: '#888'}}>+{job.skills.length - 5}</span>
                    )}
                  </div>
                )}
              </div>
              <div className="score">
                <span style={{color: job.match_score > 80 ? '#4ade80' : job.match_score > 50 ? '#facc15' : 'inherit'}}>
                  {Math.round(job.match_score)}%
                </span>
                <small>match</small>
              </div>
            </article>
          ))}
          
          {!isLoading && matches.length === 0 && (
            <div style={{gridColumn: '1 / -1', textAlign: 'center', padding: '3rem', background: 'var(--surface)'}}>
              Aucune offre ne correspond exactement  ces critres. Essayez de modifier vos filtres.
            </div>
          )}
        </div>
      </section>

      <section className="sources-section" id="sources">
        <div>
          <p className="eyebrow">Sources connectes</p>
          <h2>Un seul endroit pour suivre les offres.</h2>
        </div>
        <div className="source-list">
          {sources.map((source) => (
            <span key={source}>{source}</span>
          ))}
        </div>
      </section>
    </main>
  )
}

export default App
