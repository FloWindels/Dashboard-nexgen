"use strict";


const form =
    document.getElementById(
        "loginForm"
    );


const username =
    document.getElementById(
        "username"
    );


const password =
    document.getElementById(
        "password"
    );


const totp =
    document.getElementById(
        "totp"
    );


const button =
    document.getElementById(
        "loginButton"
    );


const errorMessage =
    document.getElementById(
        "errorMessage"
    );


form.addEventListener(
    "submit",
    async event => {

        event.preventDefault();


        errorMessage.hidden =
            true;


        button.disabled =
            true;


        button.textContent =
            "Connexion...";


        try {

            const response =
                await fetch(
                    "/api/auth/login",
                    {
                        method:
                            "POST",

                        credentials:
                            "same-origin",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                username:
                                    username.value.trim(),

                                password:
                                    password.value,

                                totp:
                                    totp.value
                                        .replace(
                                            /\D/g,
                                            ""
                                        )
                            })
                    }
                );


            let data = {};


            try {

                data =
                    await response.json();

            }
            catch {
                // réponse vide
            }


            if (!response.ok) {

                throw new Error(
                    data.detail
                    ||
                    "Connexion impossible"
                );

            }


            window.location.replace(
                "/"
            );

        }

        catch (error) {

            errorMessage.textContent =
                error.message;


            errorMessage.hidden =
                false;


            totp.value =
                "";


            totp.focus();

        }

        finally {

            button.disabled =
                false;


            button.textContent =
                "Se connecter";

        }

    }
);


/*
 * Le champ TOTP ne garde que les chiffres.
 */

totp.addEventListener(
    "input",
    () => {

        totp.value =
            totp.value
                .replace(
                    /\D/g,
                    ""
                )
                .slice(
                    0,
                    6
                );

    }
);
