// src/components/Sidebar.jsx
import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { LuLayoutDashboard, LuUpload, LuTable } from 'react-icons/lu';
import { FaFileCsv } from 'react-icons/fa';
import { FiChevronLeft, FiChevronRight } from 'react-icons/fi';

const Sidebar = () => {
  const [isMinimized, setIsMinimized] = useState(false);

  return (
    <div className={`sidebar ${isMinimized ? 'minimized' : ''}`}>
      <div className="sidebar-header">
        <div className="logo-container">
          <FaFileCsv size={25} className="logo-icon" />
          <h2 className="logo-text">GraphIQ</h2>
        </div>
        <button className="toggle-btn" onClick={() => setIsMinimized(!isMinimized)}>
          {isMinimized ? <FiChevronRight size={20} /> : <FiChevronLeft size={20} />}
        </button>
      </div>
      <nav className="sidebar-nav">
        <NavLink to="/dashboard" title="Dashboard">
          <LuLayoutDashboard size={20} /> 
          <span className="nav-text">Dashboard</span>
        </NavLink>
        <NavLink to="/upload" title="Upload">
          <LuUpload size={20} /> 
          <span className="nav-text">Upload</span>
        </NavLink>
        <NavLink to="/data-table" title="Data Table">
          <LuTable size={20} /> 
          <span className="nav-text">Data Table</span>
        </NavLink>
      </nav>
      <div className="sidebar-pro-tip">
        <span role="img" aria-label="light-bulb">💡</span>
        <div className="pro-tip-content">
          <p><strong>Pro Tip</strong></p>
          <p>Upload CSV files to get started</p>
        </div>
      </div>

      <div className="sidebar-footer">
        {/* Placeholder for Quick Actions or Profile */}
      </div>
    </div>
  );
};

export default Sidebar;