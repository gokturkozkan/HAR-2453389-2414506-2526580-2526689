HAR Mobile App – Developer Guide

This project is a React Native / Expo mobile client for a Human Activity Recognition (HAR) system.
The app handles:

User authentication (login / register)

Connecting to a set of ESP devices

Displaying connection status for each ESP

This document explains:

How the app is structured

How it expects to talk to the backend

What each UI screen does and how it fits in the flow

High-Level Architecture

Conceptually, the app has two layers:

Auth layer -> (auth)

Login screen

Register screen

Once authenticated, the user is sent into the main tab navigator.

Main app layer -> (tabs)

Home tab – welcome + “Connect” CTA for the user

Connect tab – shows ESP devices and their connection status

Communication with the backend is done via simple fetch calls to an API_URL defined in api_url.ts.

Backend Integration
API Base URL

The app uses an API_URL constant, e.g.:

<img width="615" height="141" alt="image" src="https://github.com/user-attachments/assets/5f7d8846-e3d3-4dc8-b7ee-c0e76e7379a9" />

replace PI with the IP.

Authentication Endpoints

The app expects a simple JSON API for auth. You can adapt routes, but this is the default assumption:

POST /login

Request body:

{
  "username": "string",
  "password": "string"
}


Response (success):

{
  "token": "jwt-or-session-token",
  "user": {
    "id": 1,
    "username": "string"
  }
}


Response (error, e.g. 401):

{
  "message": "Invalid username or password"
}

POST /register

Request body:

{
  "username": "string",
  "password": "string"
}

Response (success):

{
  "message": "User created",
  "user": {
    "id": 1,
    "username": "string"
  }
}

GET /esp-status

Response example:

[
  { "id": 1, "isConnected": true },
  { "id": 2, "isConnected": false },
  { "id": 3, "isConnected": true },
  { "id": 4, "isConnected": false }
]

In the app, EspStatus is:

export interface EspStatus {
  id: number;
  isConnected: boolean | null; 
}

Set null if you want a "still connecting" state, boolean -> true means connected, boolean -> false means not connected.

UI Overview
1. Login Screen

![login](https://github.com/user-attachments/assets/25f16164-86e2-45f1-974f-59eb8eab86d2)

2. Register Screen

![register](https://github.com/user-attachments/assets/a9e712ae-46e4-4dd5-8c75-7d439c926557)

3. Home Screen

![home](https://github.com/user-attachments/assets/6c6115ad-944e-4c3a-a4be-ec29af599c07)

4. Connection screen

![connection](https://github.com/user-attachments/assets/dd93a7fb-3e5e-4d74-baef-91377ee01b04)
