# 🚀 DataCraft Studio: An AI-Powered Data Cleaning Copilot

### Executive Summary
DataCraft Studio is a full-stack data cleaning and analysis platform designed to solve a critical bottleneck in data science workflows: the time-consuming process of preparing messy data for analysis. This project is a robust, asynchronous Python backend that ensures responsive performance regardless of dataset size. By leveraging an AI-powered diagnostic engine and a scalable task queue, the platform provides intelligent cleaning suggestions and performs data transformations efficiently, showcasing a production-grade approach to building modern data tooling.

---
### ✨ Core Features
* **Interactive Data Table**: An enterprise-grade AG Grid interface for viewing, sorting, and filtering large datasets.
* **Professional Dashboard**: A high-level overview of all available datasets with dynamically calculated data quality scores (missing values, duplicates, inconsistencies).
* **Automated Data Profiling**: Instantly generates a comprehensive statistics sidebar, providing at-a-glance data quality scores and detailed metrics for every column.
* **Asynchronous Backend Processing**: All heavy operations (diagnostics, standardization, column deletion) are offloaded to a Python backend, ensuring the UI remains fast and responsive at all times.
* **AI-Powered Column Diagnosis**: A feature that performs a deep statistical analysis on the backend and uses an LLM (via OpenRouter API) to provide expert, actionable recommendations for data cleaning and imputation.
* **Robust Data Operations**:
    * **Numeric Standardization**: Add standardized (Z-Score) or normalized (Min-Max) columns to the dataset.
    * **Column Deletion**: Permanently delete columns from the source file.
* **File Management**: A complete workflow for uploading new CSV files, which are then discovered and analyzed by the backend to appear on the dashboard.

---
### 🛠️ Technical Architecture

#### High-Level Overview
DataCraft Studio uses a modern, full-stack architecture with a clear separation of concerns. The frontend is a sophisticated React application responsible for user interaction and data visualization. The backend is a high-performance Python system that manages all data state and performs computationally expensive tasks asynchronously.

#### Frontend Architecture
* **Framework**: React 18 with Vite for a fast development experience.
* **Data Visualization**: AG Grid Community, customized with custom header components for displaying data types.
* **State Management**: React Context API for managing the global list of datasets and the currently active dataset.
* **UI Components**: Professional UI with toast notifications (`react-toastify`) for user feedback and a polished, animated dashboard and data table.

#### Backend Architecture
* **API Layer**: FastAPI provides robust, validated REST endpoints for all frontend-backend communication.
* **Task Queue**: Celery with a Redis broker is the core of the asynchronous architecture. It manages a queue of background jobs, ensuring that long-running tasks like data analysis do not block the API.
* **Data Processing**: Pandas is used for all core data manipulation and statistical analysis. The backend uses an in-memory cache to ensure high performance for subsequent operations on already-loaded datasets.
* **AI Integration**: A dedicated service securely communicates with the OpenRouter API, sending statistical profiles and parsing the LLM's JSON response for the frontend.

---
### 🗺️ Future Roadmap
While the current application is a robust platform, future development could focus on:
* **Backend-Driven Undo/Redo**: Implementing a professional, file-based versioning system to provide a truly non-destructive workflow.
* **Feature-Engineering**: Performing smart feature engineering with Single-Click, completely Based on Context & Columns provided.
