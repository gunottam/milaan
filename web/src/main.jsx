import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Self-hosted, not a CDN. §13 mandates IBM Plex and the demo room may not have a
// network; a webfont that fails to load takes the tabular figures with it and the
// whole layout stops aligning on the decimal.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './styles.css'
import App from './App'

createRoot(document.getElementById('root')).render(
  <StrictMode><App /></StrictMode>
)
