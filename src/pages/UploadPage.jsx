// src/pages/UploadPage.jsx
import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { useNavigate } from 'react-router-dom';
import { useDatasets } from '../context/useDatasets';
import { FaFileCsv } from 'react-icons/fa';
import { toast } from 'react-toastify';
import '../styles/UploadPage.css';

const UploadPage = () => {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const { addDataset } = useDatasets();
  const navigate = useNavigate();
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback(acceptedFiles => {
    if (acceptedFiles.length > 0) {
        setSelectedFiles([acceptedFiles[0]]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      'text/csv': ['.csv'],
    }
  });

  const handleProcessAndUpload = async () => {
    if (selectedFiles.length === 0) return;
    setIsUploading(true);
    
    const formData = new FormData();
    formData.append("file", selectedFiles[0]);

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) throw new Error((await response.json()).detail || 'File upload failed.');
      
      const result = await response.json();
      
      addDataset({
        name: result.name,
        source: 'uploaded',
        path: result.path,
      });

      toast.success(result.message);
      navigate('/dashboard');

    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="upload-page-container animated-component">
      <div className="upload-page-header" style={{ animationDelay: '0.1s' }}>
        <h1>Upload Data Files</h1>
        <p className="subtitle">Upload a CSV file to start analyzing your data</p>
      </div>

      <div className="upload-box-wrapper" style={{ animationDelay: '0.2s' }}>
        <div {...getRootProps()} className={`upload-box ${isDragActive ? 'active' : ''}`}>
          <input {...getInputProps()} />
          <div className="upload-box-content">
            <span className="upload-icon">📄</span>
            {isDragActive ?
              <p>Drop the file here ...</p> :
              <p>Drag & drop your file <br/> or click to <span className="browse-link">Choose File</span></p>
            }
            <p className="supported-formats">Supported format: CSV</p>
          </div>
        </div>
      </div>

      {selectedFiles.length > 0 && (
        <div className="selected-files-wrapper animated-component" style={{ animationDelay: '0.3s' }}>
          <h2>Selected File</h2>
          <div className="file-item">
            <FaFileCsv className="file-icon" />
            <div className="file-details">
              <span className="file-name">{selectedFiles[0].name}</span>
              <span className="file-size">{(selectedFiles[0].size / 1024 / 1024).toFixed(2)} MB</span>
            </div>
            <span className="file-type-badge">CSV</span>
          </div>
          <button onClick={handleProcessAndUpload} disabled={isUploading} className="process-button">
            {isUploading ? 'Uploading...' : 'Process and Upload File'}
          </button>
        </div>
      )}
    </div>
  );
};

export default UploadPage;