// ═══════════════════════════════════════════════
//      AUTHENTICATION LOGIC (JWT FLOW)
// ═══════════════════════════════════════════════

const authState = {
    isLoginMode: true
};

let authElements = {};

function showLoginModal() {
    // Clear token and show the full-screen login overlay
    localStorage.removeItem("jwt_token");
    if (authElements.loginModal) {
        authElements.loginModal.style.display = "flex";
    }
    // Hide the main app behind the overlay
    const appShell = document.getElementById("app-shell");
    if (appShell) {
        appShell.style.display = "none";
    }
}

function hideLoginModal() {
    // Hide the login overlay and reveal the app
    if (authElements.loginModal) {
        authElements.loginModal.style.display = "none";
    }
    const appShell = document.getElementById("app-shell");
    if (appShell) {
        appShell.style.display = "";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Cache all auth-related DOM elements
    authElements = {
        loginModal: document.getElementById("login-modal"),
        authForm: document.getElementById("auth-form"),
        authTitle: document.getElementById("auth-title"),
        authUsername: document.getElementById("auth-username"),
        authPassword: document.getElementById("auth-password"),
        authSubmitBtn: document.getElementById("auth-submit-btn"),
        authToggleBtn: document.getElementById("auth-toggle-btn"),
        authToggleMsg: document.getElementById("auth-toggle-msg"),
        authError: document.getElementById("auth-error"),
        authSuccess: document.getElementById("auth-success")
    };

    // On page load: show login if no token, otherwise reveal the app
    const existingToken = localStorage.getItem("jwt_token");
    if (!existingToken) {
        showLoginModal();
    } else {
        hideLoginModal();
    }

    // Handle Logout
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            showLoginModal();
        });
    }

    // Toggle between Login and Sign Up modes
    if (authElements.authToggleBtn) {
        authElements.authToggleBtn.addEventListener("click", (e) => {
            e.preventDefault();
            authState.isLoginMode = !authState.isLoginMode;

            // Clear any previous messages and fields
            authElements.authError.style.display = "none";
            authElements.authSuccess.style.display = "none";
            authElements.authUsername.value = "";
            authElements.authPassword.value = "";

            if (authState.isLoginMode) {
                authElements.authTitle.textContent = "Login to Video Agent";
                authElements.authSubmitBtn.textContent = "Login";
                authElements.authToggleMsg.textContent = "Create new account?";
                authElements.authToggleBtn.textContent = "Sign Up";
            } else {
                authElements.authTitle.textContent = "Sign Up to Video Agent";
                authElements.authSubmitBtn.textContent = "Sign Up";
                authElements.authToggleMsg.textContent = "Already have an account?";
                authElements.authToggleBtn.textContent = "Login here";
            }
        });
    }

    // Handle form submission for login and registration
    if (authElements.authForm) {
        authElements.authForm.addEventListener("submit", async (e) => {
            e.preventDefault();

            authElements.authError.style.display = "none";
            authElements.authSuccess.style.display = "none";

            const username = authElements.authUsername.value.trim();
            const password = authElements.authPassword.value.trim();

            if (!username || !password) {
                authElements.authError.textContent = "Both fields are required!";
                authElements.authError.style.display = "block";
                return;
            }

            const endpoint = authState.isLoginMode ? "/api/login" : "/api/register";

            try {
                const response = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json();

                if (!response.ok) {
                    authElements.authError.textContent = data.error || "Credentials error! Please check the details.";
                    authElements.authError.style.display = "block";
                    return;
                }

                if (authState.isLoginMode) {
                    // Store token and reveal the application
                    localStorage.setItem("jwt_token", data.token);
                    hideLoginModal();

                    // Load application state from server
                    if (typeof fetchState === "function") {
                        await fetchState();
                    }
                } else {
                    // Registration successful — auto-switch to login
                    authElements.authSuccess.textContent = "Account registered successfully! Switching to login...";
                    authElements.authSuccess.style.display = "block";
                    authElements.authPassword.value = "";

                    // Auto-toggle to login mode after 1.5 seconds
                    setTimeout(() => {
                        if (!authState.isLoginMode) {
                            authElements.authToggleBtn.click();
                        }
                    }, 1500);
                }
            } catch (err) {
                authElements.authError.textContent = "Server or network error. Please try again.";
                authElements.authError.style.display = "block";
            }
        });
    }
});
