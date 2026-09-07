CREATE TABLE `orchestration_events` (
	`event_id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`sequence` integer NOT NULL,
	`event_type` text NOT NULL,
	`node` text,
	`status` text NOT NULL,
	`message` text NOT NULL,
	`details_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`run_id`) REFERENCES `orchestration_runs`(`run_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `orchestration_events_run_sequence_idx` ON `orchestration_events` (`run_id`,`sequence`);--> statement-breakpoint
CREATE TABLE `orchestration_runs` (
	`run_id` text PRIMARY KEY NOT NULL,
	`incident_id` text NOT NULL,
	`application` text NOT NULL,
	`status` text DEFAULT 'running' NOT NULL,
	`current_node` text,
	`started_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`completed_at` text,
	`error` text
);
