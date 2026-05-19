import axios from 'axios';

const API_BASE = '/api/cfis/v3';

export const pipelineApi = {
    async runPipeline(payload) {
        const response = await axios.post(`${API_BASE}/pipeline/run`, payload);
        return response.data;
    },
    
    async getSnapshot(runId, stage) {
        // stages: ocr, geometry, alignment, fusion
        const response = await axios.get(`${API_BASE}/pipeline/debug/${runId}/${stage}`);
        return response.data;
    },
    
    async submitOperation(operationPayload) {
        const response = await axios.post(`${API_BASE}/hitl/operations`, operationPayload);
        return response.data;
    },
    
    async replayPipeline(runId) {
        const response = await axios.post(`${API_BASE}/hitl/rerun`, { run_id: runId });
        return response.data;
    },
    
    async getRuns() {
        const response = await axios.get(`${API_BASE}/pipeline/runs`);
        return response.data;
    },
    
    async getTimeline(runId) {
        const response = await axios.get(`${API_BASE}/pipeline/runs/${runId}/timeline`);
        return response.data;
    },
    
    async getExport(runId) {
        const response = await axios.get(`${API_BASE}/pipeline/export/${runId}`);
        return response.data;
    }
};
