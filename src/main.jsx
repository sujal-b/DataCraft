// src/main.jsx
import React, { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { DatasetProvider } from './context/DatasetContext';

// 1. Import the necessary AG Grid modules
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community';

// 2. Register the modules correctly
ModuleRegistry.registerModules([AllCommunityModule]);


createRoot(document.getElementById('root')).render(
  <StrictMode>
    <DatasetProvider>
      <App />
    </DatasetProvider>
  </StrictMode>,
);