import { useContext } from 'react';
import { DatasetContext } from './datasetContextBase';

export const useDatasets = () => useContext(DatasetContext);
