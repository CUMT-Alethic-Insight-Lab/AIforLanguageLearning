import api from './api';

export type CurrentSpeakerState = {
  classroom_session_id: number;
  current_speaker_id: number | null;
};

export class ClassroomService {
  static async getCurrentSpeaker(sessionId: number | string): Promise<CurrentSpeakerState> {
    return await api.get(`/api/v1/classroom-sessions/${sessionId}/current-speaker`) as CurrentSpeakerState;
  }

  static async setCurrentSpeaker(
    sessionId: number | string,
    studentId: number | string
  ): Promise<CurrentSpeakerState> {
    return await api.post(
      `/api/v1/classroom-sessions/${sessionId}/current-speaker`,
      { student_id: Number(studentId) }
    ) as CurrentSpeakerState;
  }

  static async clearCurrentSpeaker(sessionId: number | string): Promise<CurrentSpeakerState> {
    return await api.delete(`/api/v1/classroom-sessions/${sessionId}/current-speaker`) as CurrentSpeakerState;
  }
}
