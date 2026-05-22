{{/*
Expand the name of the chart.
*/}}
{{- define "finops-scaler.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Full name: release + chart, truncated to 63 chars.
*/}}
{{- define "finops-scaler.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "finops-scaler.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ include "finops-scaler.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (used in Deployment matchLabels).
*/}}
{{- define "finops-scaler.selectorLabels" -}}
app.kubernetes.io/name: {{ include "finops-scaler.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Dashboard full name: release + chart + "-dashboard"
*/}}
{{- define "finops-scaler.dashboard.fullname" -}}
{{- printf "%s-%s-dashboard" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Dashboard selector labels.
*/}}
{{- define "finops-scaler.dashboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "finops-scaler.name" . }}-dashboard
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
