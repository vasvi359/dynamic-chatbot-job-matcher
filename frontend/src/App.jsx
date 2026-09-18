import { useState, useRef, useEffect } from "react";
import axios from "axios";
import GapAnalysisCard from "./GapAnalysisCard";
import TopSkillsCard from "./TopSkillsCard";
import ExperienceGapCard from "./ExperienceGapCard";
import JobMatchesCard from "./JobMatchesCard";
import SavedJobsCard from "./SavedJobsCard";
import Login from "./Login";
import "./App.css";

function App() {
  const [userId, setUserId] = useState(null);
  const [userEmail, setUserEmail] = useState(null);

  const [message, setMessage] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef(null);

  const atsFileInputRef = useRef(null);
  const [atsLoading, setAtsLoading] = useState(false);

  const [chat, setChat] = useState([
    { sender: "bot", kind: "text", text: "Hello! How can I help you today?" },
  ]);

  useEffect(() => {
    const savedId = localStorage.getItem("userId");
    const savedEmail = localStorage.getItem("userEmail");
    if (savedId) {
      setUserId(Number(savedId));
      setUserEmail(savedEmail);
    }
  }, []);

  const handleLogin = (id, email) => {
    localStorage.setItem("userId", id);
    localStorage.setItem("userEmail", email);
    setUserId(id);
    setUserEmail(email);
  };

  const handleLogout = () => {
    localStorage.removeItem("userId");
    localStorage.removeItem("userEmail");
    setUserId(null);
    setUserEmail(null);
    setChat([{ sender: "bot", kind: "text", text: "Hello! How can I help you today?" }]);
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) setSelectedFile(file);
  };

  const buildBotMessage = (resData, originalQuery) => {
    if (resData.type === "chart") {
      return {
        sender: "bot",
        kind: "chart",
        chartType: resData.chart_type,
        replyText: resData.reply,
        data: resData.data,
        originalQuery,
      };
    } else if (resData.type === "text") {
      return { sender: "bot", kind: "text", text: resData.reply };
    } else {
      return { sender: "bot", kind: "text", text: JSON.stringify(resData, null, 2) };
    }
  };

  // Saved-jobs view is a client-side command (like other message kinds are
  // client/server-rendered): intercept before hitting /chat.
  const isSavedJobsQuery = (text) => {
    const lowered = (text || "").toLowerCase().trim();
    return lowered.includes("saved jobs") && lowered.length < 40;
  };

  const sendMessage = async () => {
    if (!message.trim() && !selectedFile) return;

    const userMessage = selectedFile
      ? `${message || "Analyze my resume"} 📎 ${selectedFile.name}`
      : message;

    if (!selectedFile && isSavedJobsQuery(userMessage)) {
      setChat((prev) => [
        ...prev,
        { sender: "user", kind: "text", text: userMessage },
        { sender: "bot", kind: "saved_jobs" },
      ]);
      setMessage("");
      return;
    }

    const newChat = [...chat, { sender: "user", kind: "text", text: userMessage }];
    setChat(newChat);
    setMessage("");

    try {
      let res;
      const originalQuery = message;

      if (selectedFile) {
        const formData = new FormData();
        formData.append("user_id", userId);
        formData.append("target_role", message || "a suitable role based on my resume");
        formData.append("file", selectedFile);

        res = await axios.post("http://127.0.0.1:8000/chat-with-resume", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });

        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
      } else {
        res = await axios.post("http://127.0.0.1:8000/chat", { message: userMessage, user_id: userId });
      }

      const botMsg = buildBotMessage(res.data, originalQuery);
      let nextChat = [...newChat, botMsg];

      if (selectedFile && res.data.type === "chart" && res.data.data?.targetRole) {
        try {
          const jobsRes = await axios.post("http://127.0.0.1:8000/job-matches", {
            user_id: userId,
            target_role: res.data.data.targetRole,
          });
          if (jobsRes.data.type === "job_matches") {
            nextChat = [
              ...nextChat,
              { sender: "bot", kind: "job_matches", data: jobsRes.data },
            ];
          }
        } catch (jobError) {
          console.error("Job matching failed:", jobError);
        }
      }

      setChat(nextChat);
    } catch (error) {
      console.error(error);
      setChat([...newChat, { sender: "bot", kind: "text", text: "❌ Backend not connected!" }]);
    }
  };

  const handleRefresh = async (originalQuery) => {
    const refreshText = `refresh ${originalQuery || ""}`.trim();
    setChat((prev) => [...prev, { sender: "user", kind: "text", text: `🔄 ${refreshText}` }]);

    try {
      const res = await axios.post("http://127.0.0.1:8000/chat", {
        message: refreshText,
        user_id: userId,
      });
      const botMsg = buildBotMessage(res.data, originalQuery);
      setChat((prev) => [...prev, botMsg]);
    } catch (error) {
      console.error(error);
      setChat((prev) => [...prev, { sender: "bot", kind: "text", text: "❌ Backend not connected!" }]);
    }
  };

  const handleAtsFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setChat((prev) => [
      ...prev,
      { sender: "user", kind: "text", text: `📄 Generate ATS resume from: ${file.name}` },
    ]);
    setAtsLoading(true);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await axios.post("http://127.0.0.1:8000/generate-ats-resume", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        responseType: "blob",
      });

      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "ATS_Resume.docx");
      document.body.appendChild(link);
      link.click();
      link.remove();

      setChat((prev) => [
        ...prev,
        { sender: "bot", kind: "text", text: "✅ Your ATS-friendly resume has been generated and downloaded!" },
      ]);
    } catch (error) {
      console.error(error);
      setChat((prev) => [
        ...prev,
        { sender: "bot", kind: "text", text: "❌ Something went wrong generating the ATS resume." },
      ]);
    } finally {
      setAtsLoading(false);
      if (atsFileInputRef.current) atsFileInputRef.current.value = "";
    }
  };

  if (!userId) {
    return <Login onLogin={handleLogin} />;
  }

  const renderChart = (msg) => {
    switch (msg.chartType) {
      case "top_skills":
        return <TopSkillsCard data={msg.data} />;
      case "skill_gap":
        return (
          <GapAnalysisCard
            data={{
              currentRole: msg.data.currentRole,
              currentMatch: msg.data.currentMatch,
              targetRole: msg.data.targetRole,
              targetMatch: msg.data.targetMatch,
              missingSkills: msg.data.missingSkills,
            }}
          />
        );
      case "experience_gap":
        return <ExperienceGapCard data={msg.data} />;
      default:
        return <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(msg.data, null, 2)}</pre>;
    }
  };

  return (
    <div className="app">
      <div className="app-header">
        <h1>🤖 AI Chatbot</h1>
        <div className="user-bar">
          <span>{userEmail}</span>
          <button className="logout-btn" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </div>

      <div className="chat-container">
        {chat.map((msg, index) => (
          <div key={index} className={`message ${msg.sender}`}>
            {msg.kind === "job_matches" ? (
              <JobMatchesCard data={msg.data} userId={userId} />
            ) : msg.kind === "saved_jobs" ? (
              <SavedJobsCard userId={userId} />
            ) : msg.kind === "chart" ? (
              <>
                {msg.replyText && <p style={{ margin: "0 0 8px 0" }}>{msg.replyText}</p>}
                {renderChart(msg)}
                <button
                  type="button"
                  className="refresh-btn"
                  onClick={() => handleRefresh(msg.originalQuery)}
                  title="Regenerate this analysis"
                >
                  🔄 Refresh
                </button>
              </>
            ) : (
              <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{msg.text}</pre>
            )}
          </div>
        ))}

        {selectedFile && (
          <div className="file-chip">
            📎 {selectedFile.name}
            <button
              type="button"
              className="file-chip-remove"
              onClick={() => {
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
            >
              ×
            </button>
          </div>
        )}

        <div className="input-area">
          <button type="button" className="upload-btn" onClick={() => fileInputRef.current.click()} title="Upload resume">
            📎
          </button>
          <input
            type="file"
            ref={fileInputRef}
            accept=".pdf,.docx,.txt"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />

          <button
            type="button"
            className="upload-btn"
            onClick={() => atsFileInputRef.current.click()}
            title="Generate ATS-friendly resume"
            disabled={atsLoading}
          >
            {atsLoading ? "⏳" : "📄"}
          </button>
          <input
            type="file"
            ref={atsFileInputRef}
            accept=".pdf,.docx,.txt"
            style={{ display: "none" }}
            onChange={handleAtsFileSelect}
          />

          <input
            type="text"
            placeholder={selectedFile ? "Target role (optional)..." : "Type your message..."}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") sendMessage();
            }}
          />
          <button onClick={sendMessage}>Send</button>
        </div>
      </div>
    </div>
  );
}

export default App;