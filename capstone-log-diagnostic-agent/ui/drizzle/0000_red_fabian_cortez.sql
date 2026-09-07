CREATE TABLE `human_decisions` (
	`decision_id` text PRIMARY KEY NOT NULL,
	`incident_id` text NOT NULL,
	`diagnosis_id` text,
	`decision` text NOT NULL,
	`reviewer_user_id` text NOT NULL,
	`reviewer_name` text NOT NULL,
	`reviewer_email` text,
	`comments` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`incident_id`) REFERENCES `review_items`(`incident_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `review_items` (
	`incident_id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`application` text NOT NULL,
	`environment` text NOT NULL,
	`severity` text NOT NULL,
	`symptom` text NOT NULL,
	`payload_json` text NOT NULL,
	`review_status` text DEFAULT 'pending' NOT NULL,
	`diagnosis_count` integer DEFAULT 1 NOT NULL,
	`top_confidence` real DEFAULT 0 NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
