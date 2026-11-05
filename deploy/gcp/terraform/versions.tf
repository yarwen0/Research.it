terraform {
  # 1.11 for write-only arguments: the database password reaches Cloud SQL
  # and Secret Manager without ever being written to state.
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # State holds no secrets, but it does map out the deployment. Keep it in a
  # bucket only operators can read:
  #
  # backend "gcs" {
  #   bucket = "your-terraform-state-bucket"
  #   prefix = "researchit"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
