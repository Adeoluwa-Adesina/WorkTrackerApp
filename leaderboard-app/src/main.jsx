import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
// Import SupabaseProvider from App.jsx
import { SupabaseProvider } from './App.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {/* Wrap the entire App component tree with SupabaseProvider */}
    <SupabaseProvider>
      <App />
    </SupabaseProvider>
  </React.StrictMode>,
);