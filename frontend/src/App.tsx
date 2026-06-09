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
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 12

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
          top_n: 100
        })
      })

      if (!response.ok) throw new Error("Erreur lors du matching")

      const data = await response.json()
      const filtered = (data.results || []).filter((job: JobMatch) => job.match_score >= 60)
      setMatches(filtered)
      setCurrentPage(1)
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

  // Pagination calculations
  const indexOfLastItem = currentPage * itemsPerPage
  const indexOfFirstItem = indexOfLastItem - itemsPerPage
  const currentMatches = matches.slice(indexOfFirstItem, indexOfLastItem)
  const totalPages = Math.ceil(matches.length / itemsPerPage)

  const handlePageChange = (pageNumber: number) => {
    setCurrentPage(pageNumber)
    const resultsElement = document.getElementById('results')
    if (resultsElement) {
      resultsElement.scrollIntoView({ behavior: 'smooth' })
    }
  }

  const renderPageNumbers = () => {
    const pages = []
    
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      pages.push(1)
      
      let start = Math.max(2, currentPage - 1)
      let end = Math.min(totalPages - 1, currentPage + 1)
      
      if (currentPage <= 3) {
        end = 4
      }
      if (currentPage >= totalPages - 2) {
        start = totalPages - 3
      }
      
      if (start > 2) {
        pages.push('ellipsis-start')
      }
      
      for (let i = start; i <= end; i++) {
        pages.push(i)
      }
      
      if (end < totalPages - 1) {
        pages.push('ellipsis-end')
      }
      
      pages.push(totalPages)
    }
    
    return pages.map((page, index) => {
      if (page === 'ellipsis-start' || page === 'ellipsis-end') {
        return <span key={`ellipsis-${index}`} className="pagination-ellipsis">...</span>
      }
      
      return (
        <button
          key={page}
          onClick={() => handlePageChange(page as number)}
          className={`pagination-btn page-num-btn ${currentPage === page ? 'active' : ''}`}
          aria-current={currentPage === page ? 'page' : undefined}
        >
          {page}
        </button>
      )
    })
  }

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
          <h1>Trouvez les offres au Maroc et en France qui matchent vraiment votre profil</h1>
          <p className="hero-text">
            Notre intelligence artificielle analyse plus de 3000 offres d'emploi récentes,
            extrait les compétences clés et calcule instantanément les meilleures correspondances avec votre profil.
          </p>
          <div className="hero-actions">
            <a className="primary-action" href="#search">Commencer</a>
            <a className="secondary-action" href="#results">Voir les offres</a>
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
          <p className="eyebrow">Résultats recommandés</p>
          <h2>{matches.length} opportunités trouvées</h2>
        </div>

        {error && <div style={{ color: 'red', textAlign: 'center' }}>{error}</div>}

        {isLoading && matches.length === 0 && (
          <div style={{ textAlign: 'center', padding: '2rem' }}>Chargement des recommandations ML...</div>
        )}

        <div className="job-list">
          {currentMatches.map((job, idx) => (
            <article className="job-card" key={idx}>
              <div>
                <p className="job-company">
                  {job.company || 'Entreprise Confidentielle'}
                  {job.predicted_category && <span style={{ marginLeft: 10, fontSize: '0.7em', padding: '2px 6px', background: 'var(--surface-sunken)', borderRadius: 4 }}>{job.predicted_category}</span>}
                </p>
                <h3>
                  <a href={job.job_url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                    {job.title}
                  </a>
                </h3>
                <p>
                  📍 {job.city || 'Maroc'} · {job.work_mode === 'remote' ? '🏠 Remote' : job.work_mode === 'hybrid' ? '🔄 Hybride' : '🏢 Sur site'} · {job.job_type}
                </p>

                {job.skills && job.skills.length > 0 && (
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.8rem' }}>
                    {job.skills.slice(0, 5).map(skill => (
                      <span key={skill} style={{ fontSize: '0.75rem', background: 'rgba(255,255,255,0.1)', padding: '2px 8px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.2)' }}>
                        {skill}
                      </span>
                    ))}
                    {job.skills.length > 5 && (
                      <span style={{ fontSize: '0.75rem', color: '#888' }}>+{job.skills.length - 5}</span>
                    )}
                  </div>
                )}
              </div>
              <div className="score">
                <span style={{ color: job.match_score > 80 ? '#4ade80' : job.match_score > 50 ? '#facc15' : 'inherit' }}>
                  {Math.round(job.match_score)}%
                </span>
                <small>match</small>
              </div>
            </article>
          ))}

          {!isLoading && matches.length === 0 && (
            <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '3rem', background: 'var(--surface)' }}>
              Aucune offre ne correspond exactement à ces critères. Essayez de modifier vos filtres.
            </div>
          )}
        </div>

        {/* Pagination Controls */}
        {matches.length > itemsPerPage && (
          <div className="pagination-container">
            <div className="pagination-info">
              Affichage de <strong>{indexOfFirstItem + 1}-{Math.min(indexOfLastItem, matches.length)}</strong> sur <strong>{matches.length}</strong> opportunités
            </div>
            <div className="pagination-buttons">
              <button 
                onClick={() => handlePageChange(currentPage - 1)} 
                disabled={currentPage === 1}
                className="pagination-btn arrow-btn"
                aria-label="Page précédente"
              >
                &larr; Précédent
              </button>
              
              {renderPageNumbers()}
              
              <button 
                onClick={() => handlePageChange(currentPage + 1)} 
                disabled={currentPage === totalPages}
                className="pagination-btn arrow-btn"
                aria-label="Page suivante"
              >
                Suivant &rarr;
              </button>
            </div>
          </div>
        )}
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
